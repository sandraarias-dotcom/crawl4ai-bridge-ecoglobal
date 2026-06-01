"""
server.py — Bridge MCP Ecoglobal Expeditions v4.0.0
Lee catalogo.json desde GitHub (persistente) con caché en memoria.
"""
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import json, os, re, base64, httpx
from datetime import datetime, timedelta

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
        "description": "Obtiene TODOS los detalles de una expedición: precio, fechas, incluye, no incluye, itinerario, recomendaciones, PDF.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "nombre": {
                    "type": "string",
                    "description": "Nombre o parte del nombre de la expedición"
                }
            },
            "required": ["nombre"]
        }
    }
]


def resumen_plan(exp: dict) -> str:
    nd = "Consultar con asesor"
    lineas = [f"• {exp['nombre']}"]
    lineas.append(f"  Precio: {exp.get('precio_texto', nd)} p/persona")
    if exp.get("duracion"):         lineas.append(f"  Duración: {exp['duracion']}")
    if exp.get("nivel_dificultad"): lineas.append(f"  Dificultad: {exp['nivel_dificultad']}")
    if exp.get("proximas_fechas"):  lineas.append(f"  Próx. salidas: {', '.join(exp['proximas_fechas'][:2])}")
    lineas.append(f"  URL: {exp['url']}")
    return "\n".join(lineas)


def detalle_plan(exp: dict) -> str:
    nd = "No disponible — consultar con asesor"
    lineas = [
        f"PLAN: {exp['nombre']}",
        f"Descripción: {exp.get('descripcion', nd)}",
        "",
        f"PRECIO: {exp.get('precio_texto', nd)} por persona",
    ]
    if exp.get("precio_vigencia"):   lineas.append(f"Vigencia: {exp['precio_vigencia']}")
    lineas += [
        f"Duración: {exp.get('duracion', nd)}",
        f"Dificultad: {exp.get('nivel_dificultad', nd)}",
        f"Nivel confort: {exp.get('nivel_confort', nd)}",
    ]
    if exp.get("ubicacion"):     lineas.append(f"Ubicación: {exp['ubicacion']}")
    if exp.get("ecosistema"):    lineas.append(f"Ecosistema: {exp['ecosistema']}")
    if exp.get("ciudad_salida"): lineas.append(f"Sale desde: {exp['ciudad_salida']}")

    if exp.get("proximas_fechas"):
        lineas += ["", "FECHAS:"]
        for f in exp["proximas_fechas"][:5]: lineas.append(f"  - {f}")
    else:
        lineas.append(f"\nFECHAS: {nd}")

    if exp.get("incluye"):
        lineas += ["", "INCLUYE:"]
        for i in exp["incluye"][:6]: lineas.append(f"  - {i}")
    else:
        lineas.append(f"\nINCLUYE: {nd}")

    if exp.get("no_incluye"):
        lineas += ["", "NO INCLUYE:"]
        for i in exp["no_incluye"][:5]: lineas.append(f"  - {i}")

    if exp.get("itinerario"):
        lineas += ["", "ITINERARIO:"]
        for it in exp["itinerario"][:5]: lineas.append(f"  {it}")

    if exp.get("recomendaciones"):
        lineas += ["", "RECOMENDACIONES:"]
        for r in exp["recomendaciones"][:4]: lineas.append(f"  - {r}")

    lineas += ["", f"INSCRIPCIÓN: {exp.get('como_inscribirse', nd)}", f"URL: {exp['url']}"]
    if exp.get("pdf_url"): lineas.append(f"PDF: {exp['pdf_url']}")
    return "\n".join(lineas)


async def buscar_expediciones(categoria: str = "all", busqueda: str = "") -> str:
    exps = (await cargar_catalogo()).get("expediciones", [])
    if categoria and categoria != "all":
        exps = [e for e in exps if e.get("categoria") == categoria]
    if busqueda:
        t = busqueda.lower()
        exps = [e for e in exps if t in e.get("nombre","").lower() or t in e.get("descripcion","").lower()]
    if not exps:
        return f"Sin resultados para '{categoria}'."
    total    = len(exps)
    resultado = f"Planes disponibles ({total} total, mostrando 8):\n\n"
    for exp in exps[:8]:
        resultado += resumen_plan(exp) + "\n\n"
    return resultado.strip()


async def buscar_detalle(nombre: str) -> str:
    exps = (await cargar_catalogo()).get("expediciones", [])
    t    = nombre.lower()
    hits = [e for e in exps if t in e.get("nombre","").lower()]
    if not hits: return f"No encontré '{nombre}'."
    return detalle_plan(hits[0])


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
            "serverInfo":{"name":"ecoglobal-catalogo","version":"4.0.0"},
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
            r = await buscar_detalle(args.get("nombre",""))
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
        "name": "ecoglobal-catalogo", "version": "4.0.0",
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
        "version": "4.0.0",
        "storage": "GitHub + disco local",
        "catalogo_url": GITHUB_RAW,
        "total_planes": c.get("total", 0),
        "planes_con_precio":  sum(1 for e in exps if e.get("precio_texto")),
        "planes_con_fechas":  sum(1 for e in exps if e.get("proximas_fechas")),
        "planes_con_incluye": sum(1 for e in exps if e.get("incluye")),
        "updated_at": c.get("updated_at", ""),
        "cache_activo": _cache["ts"] is not None
    }
