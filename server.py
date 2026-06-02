"""
server.py — Bridge MCP Ecoglobal Expeditions v5.2.0
Lee catalogo.json desde GitHub (persistente) con caché en memoria.
v5.2.0: detalle_expedicion acepta "seccion" (devuelve SOLO esa sección, ya
        formateada para WhatsApp y paginada con "parte" si es larga) para
        garantizar texto fiel sin que el modelo resuma ni exceda 4096 chars.
v5.1.0: detalle_expedicion con varias coincidencias devuelve LISTA para
        desambiguar (ya no elige hits[0] en silencio). Búsqueda por nombre
        normalizada sin acentos y SIN ruido de descripción.
"""
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import json, os, re, base64, httpx, unicodedata
from datetime import datetime, timedelta


def _norm(s: str) -> str:
    """minúsculas + sin acentos, para comparar nombres de forma robusta."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()

app = FastAPI()

# ── Config GitHub ────────────────────────────────────────────
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
GITHUB_USER   = "sandraarias-dotcom"
GITHUB_REPO   = "crawl4ai-bridge-ecoglobal"
GITHUB_BRANCH = "main"
GITHUB_FILE   = "catalogo.json"
GITHUB_RAW    = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{GITHUB_FILE}"
CATALOGO_FILE = os.path.join(os.path.dirname(__file__), "catalogo.json")

# Caché en memoria — refresca cada 5 min
_cache: dict = {"data": None, "ts": None}
CACHE_TTL = 300


async def cargar_catalogo() -> dict:
    """Lee catalogo.json desde GitHub raw. Caché 5 min. Fallback a disco."""
    global _cache
    ahora = datetime.utcnow()

    # Devolver caché si está fresco
    if _cache["data"] and _cache["ts"] and (ahora - _cache["ts"]).seconds < CACHE_TTL:
        return _cache["data"]

    # Leer desde GitHub raw (URL pública, sin auth)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(GITHUB_RAW)
            if resp.status_code == 200:
                data = resp.json()
                _cache = {"data": data, "ts": ahora}
                return data
    except Exception as e:
        print(f"GitHub raw error: {e}")

    # Fallback: disco local
    try:
        with open(CATALOGO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            _cache = {"data": data, "ts": ahora}
            return data
    except Exception:
        return {"expediciones": [], "total": 0, "updated_at": ""}


def invalidar_cache():
    global _cache
    _cache = {"data": None, "ts": None}


# ── Tools MCP ────────────────────────────────────────────────
TOOLS = [
    {
        "name": "listar_expediciones",
        "description": "Obtiene el catálogo de expediciones de Ecoglobal con precios, fechas y detalles reales. Úsalo siempre que el cliente pregunte qué opciones hay según tipo de naturaleza.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "description": "Filtro: 'caminatas' montaña/páramo/cerros, 'destinos' mar/selva/desierto, 'actividades' ballenas/rafting, 'all' todo",
                    "default": "all"
                },
                "busqueda": {
                    "type": "string",
                    "description": "Término opcional para filtrar por nombre"
                }
            }
        }
    },
    {
        "name": "detalle_expedicion",
        "description": "Detalle de una expedición. Sin 'seccion' devuelve el resumen (cabecera + descripción + lista de secciones disponibles). Con 'seccion' devuelve SOLO esa sección, ya formateada para WhatsApp y lista para copiar TAL CUAL (no resumir). Si la sección es larga se entrega por partes con 'parte'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "nombre": {
                    "type": "string",
                    "description": "Nombre o parte del nombre de la expedición"
                },
                "seccion": {
                    "type": "string",
                    "description": "Opcional. Sección a mostrar: descripcion, fechas, precio, inscripcion, incluye, no_incluye, itinerario, recomendaciones, pdf"
                },
                "parte": {
                    "type": "integer",
                    "description": "Opcional (def. 1). Número de parte cuando la sección es larga y se entrega paginada."
                }
            },
            "required": ["nombre"]
        }
    }
]


def resumen_plan(exp: dict) -> str:
    nd = "Consultar con asesor"
    lineas = [f"• {exp['nombre']}"]
    lineas.append(f"  Precio desde: {exp.get('precio_texto', nd)} p/persona")
    if exp.get("duracion"):
        lineas.append(f"  Duración: {exp['duracion']}")
    lineas.append(f"  URL: {exp['url']}")
    return "\n".join(lineas)


# ── Formato WhatsApp + paginación de secciones ───────────────
_WA_LIMITE = 3900  # margen seguro por debajo del tope de 4096 de WhatsApp


def _a_whatsapp(texto: str) -> str:
    """Convierte el markdown del catálogo a formato WhatsApp, SIN alterar el
    contenido (no resume, no reescribe; solo cambia marcas de formato)."""
    t = texto
    t = re.sub(r"^#{1,6}\s*(.+?)\s*$", r"*\1*", t, flags=re.MULTILINE)  # ## Título -> *Título*
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1: \2", t)       # [texto](url) -> texto: url
    t = re.sub(r"^(\s*)[\*\-]\s+", r"\1• ", t, flags=re.MULTILINE)      # viñetas -> •
    t = re.sub(r"\*{2,}", "*", t)                                       # **/*** -> * (negrita WhatsApp)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _chunk(texto: str, limite: int = _WA_LIMITE):
    """Parte el texto en bloques <= limite, respetando párrafos y sin cortar
    palabras. Nunca elimina contenido."""
    parrafos = texto.split("\n\n")
    partes, actual = [], ""
    for p in parrafos:
        if not actual:
            actual = p
        elif len(actual) + 2 + len(p) <= limite:
            actual += "\n\n" + p
        else:
            partes.append(actual)
            actual = p
        # párrafo individual más largo que el límite: cortar por líneas
        while len(actual) > limite:
            corte = actual.rfind("\n", 0, limite)
            if corte <= 0:
                corte = limite
            partes.append(actual[:corte].rstrip())
            actual = actual[corte:].lstrip()
    if actual:
        partes.append(actual)
    return partes or [texto[:limite]]


# Alias amigables -> clave real en detalles
_SECCION_ALIAS = {
    "descripcion": "descripcion_completa", "descripción": "descripcion_completa",
    "descripcion_completa": "descripcion_completa",
    "localizacion": "localizacion", "localización": "localizacion", "ubicacion": "localizacion",
    "fechas": "fechas", "fecha": "fechas",
    "precio": "precio_y_forma_de_pago", "pago": "precio_y_forma_de_pago",
    "precio_y_forma_de_pago": "precio_y_forma_de_pago", "forma de pago": "precio_y_forma_de_pago",
    "inscripcion": "como_inscribirse", "inscripción": "como_inscribirse",
    "como_inscribirse": "como_inscribirse", "como inscribirse": "como_inscribirse",
    "incluye": "incluye",
    "no_incluye": "no_incluye", "no incluye": "no_incluye", "noincluye": "no_incluye",
    "itinerario": "itinerario",
    "recomendaciones": "recomendaciones", "recomendacion": "recomendaciones",
}
_TITULO_SECCION = {clave: titulo for titulo, clave in [
    ("DESCRIPCIÓN", "descripcion_completa"), ("LOCALIZACIÓN", "localizacion"),
    ("FECHAS", "fechas"), ("PRECIO Y FORMA DE PAGO", "precio_y_forma_de_pago"),
    ("CÓMO INSCRIBIRSE", "como_inscribirse"), ("INCLUYE", "incluye"),
    ("NO INCLUYE", "no_incluye"), ("ITINERARIO", "itinerario"),
    ("RECOMENDACIONES", "recomendaciones"),
]}


# Orden y títulos legibles de las secciones para el detalle
_SECCIONES_DETALLE = [
    ("DESCRIPCIÓN",            "descripcion_completa"),
    ("LOCALIZACIÓN",           "localizacion"),
    ("FECHAS",                 "fechas"),
    ("PRECIO Y FORMA DE PAGO", "precio_y_forma_de_pago"),
    ("CÓMO INSCRIBIRSE",       "como_inscribirse"),
    ("INCLUYE",                "incluye"),
    ("NO INCLUYE",             "no_incluye"),
    ("ITINERARIO",             "itinerario"),
    ("RECOMENDACIONES",        "recomendaciones"),
]


def detalle_plan(exp: dict) -> str:
    """Devuelve el contenido FIEL del plan, sección por sección, tal como en la web."""
    nd = "No disponible — consultar con asesor"
    d = exp.get("detalles", {}) or {}
    lineas = [f"PLAN: {exp.get('nombre', '')}"]
    if exp.get("precio_texto"):
        lineas.append(f"PRECIO DESDE: {exp['precio_texto']} por persona")
    if exp.get("duracion"):
        lineas.append(f"DURACIÓN: {exp['duracion']}")

    for titulo, clave in _SECCIONES_DETALLE:
        contenido = d.get(clave)
        if contenido:
            lineas.append(f"\n=== {titulo} ===\n{contenido}")

    lineas.append(f"\nURL: {exp.get('url', '')}")
    if exp.get("pdf_url"):
        lineas.append(f"PDF: {exp['pdf_url']}")
    return "\n".join(lineas)


async def buscar_expediciones(categoria: str = "all", busqueda: str = "") -> str:
    exps = (await cargar_catalogo()).get("expediciones", [])
    if categoria and categoria != "all":
        exps = [e for e in exps if e.get("categoria") == categoria]
    if busqueda:
        t = _norm(busqueda)
        # Match SOLO por nombre (normalizado sin acentos). Antes también
        # matcheaba descripcion_completa, lo que metía ruido: planes que
        # solo MENCIONAN el término aparecían como si fueran ese lugar.
        exps = [e for e in exps if t in _norm(e.get("nombre", ""))]
    if not exps:
        criterio = busqueda or categoria
        return f"Sin resultados para '{criterio}'."
    total     = len(exps)
    mostrados = min(total, 8)
    resultado = f"Planes disponibles ({total} total, mostrando {mostrados}):\n\n"
    for exp in exps[:8]:
        resultado += resumen_plan(exp) + "\n\n"
    return resultado.strip()


async def buscar_detalle(nombre: str, seccion: str = "", parte: int = 1) -> str:
    exps = (await cargar_catalogo()).get("expediciones", [])
    t    = _norm(nombre)
    hits = [e for e in exps if t in _norm(e.get("nombre", ""))]
    if not hits:
        return f"No encontré ninguna expedición que coincida con '{nombre}'."
    # VARIAS coincidencias → desambiguar antes de detallar (sin elegir una).
    if len(hits) > 1:
        muestra = hits[:12]
        cab = (f"Hay {len(hits)} planes que coinciden con '{nombre}'. ¿Cuál quieres?"
               if len(hits) <= 12 else
               f"Hay {len(hits)} planes que coinciden con '{nombre}'. Afina (zona o nombre). Algunos:")
        lineas = [cab]
        for e in muestra:
            precio = e.get("precio_texto")
            lineas.append(f"• {e.get('nombre', '')}" + (f" — desde {precio}" if precio else ""))
        return "\n".join(lineas)

    exp = hits[0]
    d   = exp.get("detalles", {}) or {}

    # ── Sin 'seccion': resumen = cabecera + secciones disponibles ──
    if not seccion:
        desc = d.get("descripcion_completa", "") or ""
        msub  = re.search(r"^#{1,6}\s*(.+)$", desc, flags=re.MULTILINE)
        mdest = re.search(r"\[([^\]]+)\]\((?:https?://[^)]*/destino/[^)]*)\)", desc)
        lineas = [f"PLAN: {exp.get('nombre', '')}"]
        if msub:  lineas.append(f"SUBTITULO: {msub.group(1).strip()}")
        if mdest: lineas.append(f"DESTINO (encabezado): {mdest.group(1).strip()}")
        if exp.get("precio_texto"): lineas.append(f"PRECIO DESDE: {exp['precio_texto']} por persona")
        if exp.get("duracion"):     lineas.append(f"DURACIÓN: {exp['duracion']}")
        lineas.append(f"URL: {exp.get('url', '')}")
        if exp.get("pdf_url"):      lineas.append(f"PDF: {exp['pdf_url']}")
        disp = [titulo for titulo, clave in _SECCIONES_DETALLE if d.get(clave)]
        if exp.get("pdf_url"): disp.append("PDF")
        lineas.append("\nSECCIONES DISPONIBLES: " + ", ".join(disp))
        lineas.append("(Pide una sección con detalle_expedicion(seccion=...). Cada una se "
                      "entrega TAL CUAL, sin resumir.)")
        return "\n".join(lineas)

    # ── Con 'seccion': devolver SOLO esa sección, WA-formateada y paginada ──
    s = _norm(seccion)
    if s == "pdf":
        return f"PDF del plan: {exp.get('pdf_url', '(no disponible)')}"
    clave = _SECCION_ALIAS.get(s)
    if not clave:
        return f"Sección '{seccion}' no reconocida."
    contenido = d.get(clave)
    if not contenido:
        titulo = _TITULO_SECCION.get(clave, seccion)
        return f"La sección '{titulo}' no está disponible para este plan; ofrece consultar con un asesor."

    partes = _chunk(_a_whatsapp(contenido))
    n = len(partes)
    try:    parte = int(parte)
    except Exception: parte = 1
    parte = max(1, min(parte, n))
    bloque = partes[parte - 1]
    if n == 1:
        return bloque
    titulo = _TITULO_SECCION.get(clave, seccion)
    encab  = f"({titulo} — parte {parte} de {n})\n\n"
    pie    = (f"\n\n— Escribe \"más\" para la parte {parte + 1} de {n}."
              if parte < n else f"\n\n— Fin de {titulo}.")
    return encab + bloque + pie


# ── MCP JSON-RPC 2.0 ─────────────────────────────────────────
@app.post("/mcp")
async def mcp_handler(request: Request):
    body   = await request.json()
    rid    = body.get("id", 1)
    method = body.get("method", "")
    params = body.get("params", {})

    if method == "initialize":
        return JSONResponse({"jsonrpc":"2.0","id":rid,"result":{
            "protocolVersion":"2024-11-05",
            "serverInfo":{"name":"ecoglobal-catalogo","version":"5.2.0"},
            "capabilities":{"tools":{}}
        }})

    if method == "tools/list":
        return JSONResponse({"jsonrpc":"2.0","id":rid,"result":{"tools":TOOLS}})

    if method == "tools/call":
        tn   = params.get("name","")
        args = params.get("arguments",{})
        if tn == "listar_expediciones":
            r = await buscar_expediciones(args.get("categoria","all"), args.get("busqueda",""))
        elif tn == "detalle_expedicion":
            r = await buscar_detalle(
                args.get("nombre", ""),
                args.get("seccion", ""),
                args.get("parte", 1),
            )
        else:
            return JSONResponse({"jsonrpc":"2.0","id":rid,
                "error":{"code":-32601,"message":f"Tool '{tn}' no encontrada"}})
        return JSONResponse({"jsonrpc":"2.0","id":rid,
            "result":{"content":[{"type":"text","text":r}]}})

    if method.startswith("notifications/"):
        return JSONResponse({"jsonrpc":"2.0","id":rid,"result":{}})

    return JSONResponse({"jsonrpc":"2.0","id":rid,
        "error":{"code":-32601,"message":f"Método '{method}' no reconocido"}})


# ── Trigger manual cron ──────────────────────────────────────
@app.post("/admin/actualizar-catalogo")
async def trigger_cron(background_tasks: BackgroundTasks):
    async def run():
        try:
            from cron_actualizar_catalogo import actualizar_catalogo
            await actualizar_catalogo()
            invalidar_cache()
        except Exception as e:
            print(f"Error cron: {e}")
    background_tasks.add_task(run)
    return {"status": "Actualización iniciada — revisa los logs"}


# ── Descubrimiento GET ───────────────────────────────────────
@app.get("/mcp")
async def mcp_discovery():
    c = await cargar_catalogo()
    return {
        "name": "ecoglobal-catalogo", "version": "5.2.0",
        "total_planes": c.get("total", 0),
        "updated_at": c.get("updated_at", ""),
        "catalogo_url": GITHUB_RAW,
        "tools": TOOLS
    }


# ── Health ───────────────────────────────────────────────────
@app.get("/health")
async def health():
    c    = await cargar_catalogo()
    exps = c.get("expediciones", [])
    return {
        "status": "ok",
        "version": "5.2.0",
        "storage": "GitHub + disco local",
        "catalogo_url": GITHUB_RAW,
        "total_planes": c.get("total", 0),
        "planes_con_precio":     sum(1 for e in exps if e.get("precio_texto")),
        "planes_con_detalles":   sum(1 for e in exps if e.get("detalles")),
        "planes_con_itinerario": sum(1 for e in exps if (e.get("detalles") or {}).get("itinerario")),
        "updated_at": c.get("updated_at", ""),
        "cache_activo": _cache["ts"] is not None
    }
