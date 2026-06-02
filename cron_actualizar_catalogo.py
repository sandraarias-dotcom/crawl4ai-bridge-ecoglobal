"""
cron_actualizar_catalogo.py — Ecoglobal Expeditions v5.0.0
Autodescubre + extrae FIEL cada sección de la página + guarda catalogo.json en GitHub.
Extracción por secciones (HTML -> markdown -> split por encabezados H2), sin truncado.
El archivo es visible en:
https://github.com/sandraarias-dotcom/crawl4ai-bridge-ecoglobal/blob/main/catalogo.json
Railway cron: 0 8 * * * (8AM UTC = 3AM Colombia)

Dependencias añadidas (agregar a requirements.txt): markdownify, beautifulsoup4
"""

import asyncio
import json
import os
import re
import base64
import unicodedata
import httpx
from datetime import datetime
from markdownify import markdownify as html_a_md

# ── Config ───────────────────────────────────────────────────
CATALOGO_FILE  = os.path.join(os.path.dirname(__file__), "catalogo.json")
ALL_URL        = "https://ecoglobalexpeditions.com/all/"
BASE_URL       = "https://ecoglobalexpeditions.com"

# GitHub — variables de entorno en Railway
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN")
GITHUB_USER    = "sandraarias-dotcom"
GITHUB_REPO    = "crawl4ai-bridge-ecoglobal"
GITHUB_BRANCH  = "main"
GITHUB_FILE    = "catalogo.json"
GITHUB_API     = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{GITHUB_FILE}"

HEADERS_HTTP = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CO,es;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
}

# Páginas de sistema WordPress / institucionales — nunca son planes.
# Se filtran en el autodescubrimiento y se purgan del catálogo en cada corrida.
PATRON_NO_PLAN = re.compile(
    r"ecoglobalexpeditions\.com/"
    r"(?:wp-json|wp-admin|wp-content|feed|sitemap|robots|"
    r"politica-|terminos|privacidad|aviso-legal|cookies|condiciones-)",
    re.IGNORECASE,
)

# Encabezados de sección del tema Ecoglobal -> clave en el JSON.
# Estos H2 son consistentes en todas las páginas de plan.
SECCIONES = {
    "localizacion": "localizacion",
    "fechas": "fechas",
    "precio y forma de pago": "precio_y_forma_de_pago",
    "como inscribirse": "como_inscribirse",
    "incluye": "incluye",
    "no incluye": "no_incluye",
    "itinerario": "itinerario",
    "recomendaciones": "recomendaciones",
}
# Encabezados que son solo divisores, sin cuerpo propio
SECCIONES_IGNORAR = {"detalles", "comparte"}


# ── GitHub helpers ───────────────────────────────────────────

async def cargar_catalogo_github() -> dict:
    """Carga catalogo.json desde GitHub. Fallback al archivo local."""
    if not GITHUB_TOKEN:
        print("  ⚠️  GITHUB_TOKEN no configurado — usando archivo local")
        return cargar_catalogo_local()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                GITHUB_API,
                headers={
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                contenido = base64.b64decode(data["content"]).decode("utf-8")
                catalogo = json.loads(contenido)
                print(f"  ✅ Catálogo cargado desde GitHub ({catalogo.get('total', 0)} planes)")
                return catalogo
            else:
                print(f"  ⚠️  GitHub respondió {resp.status_code} — usando archivo local")
                return cargar_catalogo_local()
    except Exception as e:
        print(f"  ⚠️  Error GitHub: {e} — usando archivo local")
        return cargar_catalogo_local()


def cargar_catalogo_local() -> dict:
    try:
        with open(CATALOGO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"updated_at": "", "total": 0, "expediciones": []}


async def guardar_catalogo_github(catalogo: dict):
    """
    Guarda catalogo.json en GitHub via API.
    Hace un commit con mensaje y timestamp.
    El archivo queda visible en el repo.
    """
    contenido_str  = json.dumps(catalogo, ensure_ascii=False, indent=2)
    contenido_b64  = base64.b64encode(contenido_str.encode("utf-8")).decode("utf-8")

    # 1. Guardar en disco local primero (respaldo)
    with open(CATALOGO_FILE, "w", encoding="utf-8") as f:
        f.write(contenido_str)
    print(f"  ✅ Guardado en disco local")

    # 2. Guardar en GitHub
    if not GITHUB_TOKEN:
        print("  ⚠️  GITHUB_TOKEN no configurado — solo guardado local")
        return

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Obtener el SHA actual del archivo (necesario para actualizar)
            resp_get = await client.get(
                GITHUB_API,
                headers={
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json"
                }
            )
            sha = None
            if resp_get.status_code == 200:
                sha = resp_get.json().get("sha")

            # Commit con el nuevo contenido
            payload = {
                "message": f"🤖 Cron actualización catálogo — {catalogo.get('updated_at', '')} | {catalogo.get('total', 0)} planes | {sum(1 for e in catalogo.get('expediciones',[]) if e.get('precio_texto'))} precios",
                "content": contenido_b64,
                "branch": GITHUB_BRANCH,
            }
            if sha:
                payload["sha"] = sha

            resp_put = await client.put(
                GITHUB_API,
                headers={
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json"
                },
                json=payload
            )

            if resp_put.status_code in (200, 201):
                commit_sha = resp_put.json().get("commit", {}).get("sha", "")[:7]
                print(f"  ✅ Guardado en GitHub — commit {commit_sha}")
                print(f"  🔗 Ver en: https://github.com/{GITHUB_USER}/{GITHUB_REPO}/blob/{GITHUB_BRANCH}/{GITHUB_FILE}")
            else:
                print(f"  ❌ Error GitHub PUT: {resp_put.status_code} — {resp_put.text[:200]}")

    except Exception as e:
        print(f"  ❌ Error guardando en GitHub: {e}")


# ── Utilidades ───────────────────────────────────────────────

def limpiar_texto(texto: str) -> str:
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto.replace('[:es]','').replace('[:en]','').replace('[:]','')


def inferir_categoria(url: str, nombre: str) -> str:
    u, n = url.lower(), nombre.lower()
    if any(x in u or x in n for x in ["caminata","camino","ascenso","paramo",
                                        "travesia","puebliada","sendero"]):
        return "caminatas"
    if any(x in u or x in n for x in ["expedicion","safari","desierto","tatacoa",
                                        "amazonas","guajira","capurgana","roraima",
                                        "guaviare","putumayo","caqueta","paramillo","guanapalo"]):
        return "destinos"
    if any(x in u or x in n for x in ["ballenas","tortugas","rafting","fotografia",
                                        "curso","avistamiento","pasadia","liberacion"]):
        return "actividades"
    return "caminatas"


async def get_html(url: str) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=20, follow_redirects=True, headers=HEADERS_HTTP
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        print(f"    ⚠️  Error: {e}")
        return ""


# ── PASO 0: Autodescubrimiento ───────────────────────────────

async def descubrir_planes_nuevos(urls_actuales: set) -> list:
    print("\n🔍 PASO 0 — Autodescubrimiento de planes nuevos...")
    html = await get_html(ALL_URL)
    if not html:
        print("  ❌ No se pudo acceder a /all/")
        return []

    urls_sitio = set(re.findall(
        r'href=["\'](' + re.escape(BASE_URL) + r'/[a-z0-9_-]+/)["\']', html
    ))
    excluir = {
        f"{BASE_URL}/caminatas/", f"{BASE_URL}/destinos/",
        f"{BASE_URL}/actividades/", f"{BASE_URL}/contacto/",
        f"{BASE_URL}/preguntanos/", f"{BASE_URL}/all/",
        f"{BASE_URL}/", f"{BASE_URL}/en/",
    }
    urls_planes = urls_sitio - excluir
    # Descartar páginas de sistema / institucionales (wp-json, politicas, etc.)
    descartadas = {u for u in urls_planes if PATRON_NO_PLAN.search(u)}
    if descartadas:
        print(f"  🚫 Descartadas (no-plan): {len(descartadas)}")
        for u in sorted(descartadas):
            print(f"     - {u}")
    urls_planes = urls_planes - descartadas
    urls_nuevas = urls_planes - urls_actuales

    print(f"  URLs en el sitio:   {len(urls_planes)}")
    print(f"  URLs en catálogo:   {len(urls_actuales)}")
    print(f"  URLs nuevas:        {len(urls_nuevas)}")

    if not urls_nuevas:
        print("  ✅ No hay planes nuevos")
        return []

    nuevos = []
    for url in urls_nuevas:
        html_plan = await get_html(url)
        nombre = "Plan sin nombre"
        if html_plan:
            h1 = re.search(r'<h1[^>]*>\s*([^<]+)\s*</h1>', html_plan)
            nombre = limpiar_texto(h1.group(1)) if h1 else \
                url.rstrip('/').split('/')[-1].replace('-',' ').replace('_',' ').title()
        nuevos.append({
            "id": None, "nombre": nombre,
            "categoria": inferir_categoria(url, nombre),
            "url": url, "detalles": {}
        })
        print(f"  ➕ {nombre[:60]}")
        await asyncio.sleep(0.5)
    return nuevos


# ── PASO 1: Extracción FIEL por secciones ────────────────────

def _norm(s: str) -> str:
    """minúsculas, sin acentos, sin signos, espacios colapsados (para comparar labels)."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[¿?¡!:.\u2013\u2014-]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _limpiar_seccion(texto: str) -> str:
    """Limpieza ligera del markdown de una sección, preservando texto, listas y negritas."""
    texto = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", texto)      # imágenes (no aportan al agente)
    lineas = []
    for ln in texto.split("\n"):
        # descartar líneas que son solo anclas/CTA tipo [Explora](#...) [Reserva](#...)
        if re.fullmatch(r"\s*(?:\[[^\]]*\]\(#[^)]*\)\s*)+", ln):
            continue
        lineas.append(ln.rstrip())
    texto = "\n".join(lineas)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def extraer_datos_plan(html: str) -> dict:
    """
    Extracción FIEL: convierte la página a markdown y captura cada sección
    (Localización, Fechas, Precio, Incluye, No incluye, Itinerario, etc.)
    completa y verbatim. Sin truncado ni regex frágil sobre texto libre.
    """
    datos = {
        "nombre": None,
        "precio_texto": None, "precio_desde": None,
        "duracion": None, "duracion_dias": None,
        "pdf_url": None,
        "detalles": {},
    }
    if not html:
        return datos

    md = html_a_md(html, heading_style="ATX", strip=["script", "style"])

    # PDF (capturar antes de recortar la región)
    pdf = re.search(r"\(([^)]*convert-to-pdf[^)]*)\)", md)
    if pdf:
        datos["pdf_url"] = pdf.group(1).replace("&amp;", "&")

    # Título del plan (primer H1)
    m_h1 = re.search(r"^#\s+(.+)$", md, re.MULTILINE)
    if not m_h1:
        return datos
    datos["nombre"] = m_h1.group(1).strip()

    # Recortar región útil: desde el H1 hasta el bloque de "Descargar como PDF" / "Comparte"
    inicio = m_h1.start()
    fin = len(md)
    for marcador in (r"^#{1,6}\s*\[?Descargar como PDF", r"^Comparte\s*:", r"convert-to-pdf"):
        mm = re.search(marcador, md[inicio:], re.MULTILINE | re.IGNORECASE)
        if mm:
            fin = min(fin, inicio + mm.start())
    region = md[inicio:fin]

    # Partir por encabezados H2 (## Label)
    partes = re.split(r"^##\s+(.+)$", region, flags=re.MULTILINE)

    # partes[0] = bloque entre el H1 y el primer H2 = descripción completa
    descripcion = re.sub(r"^#\s+.+$", "", partes[0], count=1, flags=re.MULTILINE)
    desc_limpia = _limpiar_seccion(descripcion)
    if desc_limpia:
        datos["detalles"]["descripcion_completa"] = desc_limpia

    # Pares (label, contenido) para cada sección del acordeón
    for i in range(1, len(partes), 2):
        label = _norm(partes[i])
        if label in SECCIONES_IGNORAR:
            continue
        clave = SECCIONES.get(label)
        if not clave:
            continue
        contenido = _limpiar_seccion(partes[i + 1] if i + 1 < len(partes) else "")
        if contenido:
            datos["detalles"][clave] = contenido

    # Campos estructurados (solo para listar/filtrar; el detalle vive en 'detalles')
    precios = re.findall(r"\$\s*([\d]{1,3}(?:[.,]\d{3})+)", region)
    if precios:
        datos["precio_texto"] = f"${precios[0].replace(' ', '')}"
        try:
            datos["precio_desde"] = int(precios[0].replace(".", "").replace(",", ""))
        except ValueError:
            pass
    dur = re.search(r"(\d+)\s*d[íi]as?", region.lower())
    if dur:
        datos["duracion_dias"] = int(dur.group(1))
        datos["duracion"] = f"{dur.group(1)} días"

    return datos


# ── PROCESO PRINCIPAL ────────────────────────────────────────

async def actualizar_catalogo():
    import sys
    inicio = datetime.now()
    print(f"\n{'='*55}")
    print(f"🚀 Actualización Ecoglobal: {inicio.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    catalogo     = await cargar_catalogo_github()
    expediciones = catalogo.get("expediciones", [])

    # Purga auto-sanadora: elimina páginas de sistema/institucionales
    # que se hayan colado en corridas anteriores (wp-json, politicas, etc.)
    antes = len(expediciones)
    expediciones = [e for e in expediciones if not PATRON_NO_PLAN.search(e.get("url", ""))]
    purgadas = antes - len(expediciones)
    if purgadas:
        print(f"  🧹 Purgadas {purgadas} entradas no-plan del catálogo existente")

    urls_actuales = {exp["url"] for exp in expediciones}

    # PASO 0: Autodescubrimiento
    nuevos = await descubrir_planes_nuevos(urls_actuales)
    if nuevos:
        max_id = max((e.get("id") or 0 for e in expediciones), default=0)
        for i, n in enumerate(nuevos, 1):
            n["id"] = max_id + i
        expediciones.extend(nuevos)
        print(f"\n  ✅ {len(nuevos)} planes nuevos agregados")

    # PASO 1: Extracción fiel de cada plan
    total = len(expediciones)
    print(f"\n📦 PASO 1 — Extrayendo (fiel) {total} planes...")

    actualizadas = con_precio = con_secciones = 0
    errores = []

    for i, exp in enumerate(expediciones):
        url    = exp.get("url", "")
        nombre = exp.get("nombre", "")
        print(f"  [{i+1}/{total}] {nombre[:55]}...")

        html = await get_html(url)
        if html:
            datos = extraer_datos_plan(html)
            # Sobrescribir con el contenido actual de la página (fiel cada corrida)
            if datos.get("nombre"):        exp["nombre"] = datos["nombre"]
            exp["categoria"] = inferir_categoria(url, exp.get("nombre", ""))
            for k in ("precio_texto", "precio_desde", "duracion", "duracion_dias", "pdf_url"):
                if datos.get(k) is not None:
                    exp[k] = datos[k]
            exp["detalles"] = datos.get("detalles", {})
            # limpiar campos del esquema viejo si existían
            for viejo in ("descripcion", "proximas_fechas", "incluye", "no_incluye",
                          "itinerario", "recomendaciones", "nivel_dificultad",
                          "nivel_confort", "ecosistema", "clima", "elevacion",
                          "ubicacion", "distancia", "ciudad_salida", "atractivos",
                          "como_inscribirse", "precio_vigencia", "descripcion_completa"):
                exp.pop(viejo, None)

            actualizadas += 1
            n_sec = len(exp["detalles"])
            if datos.get("precio_texto"): con_precio += 1
            if n_sec:                     con_secciones += 1
            print(f"    ✅ {datos.get('precio_texto','—')} | {n_sec} secciones")
        else:
            errores.append(nombre[:40])
            print(f"    ❌ Sin contenido")

        await asyncio.sleep(1.5)

    # PASO 2: Guardar en GitHub + disco
    print(f"\n💾 PASO 2 — Guardando catálogo en GitHub...")
    catalogo["updated_at"]   = datetime.now().strftime("%Y-%m-%d %H:%M")
    catalogo["total"]        = len(expediciones)
    catalogo["expediciones"] = expediciones
    await guardar_catalogo_github(catalogo)

    fin = datetime.now()
    seg = (fin - inicio).seconds
    print(f"\n{'='*55}")
    print(f"✅ Completado en {seg}s")
    print(f"   Total planes:  {len(expediciones)}")
    print(f"   Actualizadas:  {actualizadas}")
    print(f"   Con precio:    {con_precio}")
    print(f"   Con secciones: {con_secciones}")
    if errores: print(f"   Errores:       {errores[:3]}")
    print(f"{'='*55}\n")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(actualizar_catalogo())
