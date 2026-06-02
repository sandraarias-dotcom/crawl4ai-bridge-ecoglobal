"""
cron_actualizar_catalogo.py — Ecoglobal Expeditions v4.0.0
Autodescubre + enriquece planes + guarda catalogo.json en GitHub.
El archivo es visible en:
https://github.com/sandraarias-dotcom/crawl4ai-bridge-ecoglobal/blob/main/catalogo.json
Railway cron: 0 8 * * * (8AM UTC = 3AM Colombia)
"""

import asyncio
import json
import os
import re
import base64
import httpx
from datetime import datetime

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
            "descripcion": "", "url": url
        })
        print(f"  ➕ {nombre[:60]}")
        await asyncio.sleep(0.5)
    return nuevos


# ── PASO 1: Extracción de datos ──────────────────────────────

def extraer_datos_plan(html: str) -> dict:
    datos = {
        "precio_desde": None, "precio_texto": None, "precio_vigencia": None,
        "duracion": None, "duracion_dias": None,
        "nivel_dificultad": None, "nivel_confort": None,
        "ecosistema": None, "clima": None, "elevacion": None,
        "ubicacion": None, "distancia": None, "ciudad_salida": None,
        "atractivos": [], "proximas_fechas": [],
        "incluye": [], "no_incluye": [],
        "itinerario": [], "recomendaciones": [],
        "como_inscribirse": None, "pdf_url": None,
        "descripcion_completa": None,
    }
    if not html:
        return datos

    hl = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    hl = re.sub(r'<style[^>]*>.*?</style>',  '', hl,   flags=re.DOTALL)
    tx = re.sub(r'<[^>]+>', ' ', hl)
    tx = re.sub(r'\s+', ' ', tx).strip()
    tl = tx.lower()

    # Precio
    precios = re.findall(r'\$\s*([\d]{1,3}(?:[.,]\d{3})+)', tx)
    if precios:
        ps = precios[0].replace('.','').replace(',','')
        try:
            datos["precio_desde"] = int(ps)
            datos["precio_texto"]  = f"${precios[0]}"
        except:
            datos["precio_texto"]  = f"${precios[0]}"
    v = re.search(r'precio[s]?\s+(?:para\s+el?\s+año\s+)?(\d{4})', tl)
    if v: datos["precio_vigencia"] = v.group(1)

    # Duración
    d = re.search(r'(\d+)\s*d[íi]as?\s*(?:y\s*(\d+)\s*noches?)?', tl)
    if d:
        datos["duracion_dias"] = int(d.group(1))
        datos["duracion"] = f"{d.group(1)} días" + (f" y {d.group(2)} noches" if d.group(2) else "")
    elif re.search(r'un d[íi]a|1 d[íi]a|d[íi]a completo', tl):
        datos["duracion_dias"] = 1
        datos["duracion"] = "1 día"

    # Dificultad
    for k, v2 in [("nevado","Nevado"),("páramo-volcán","Páramo-Volcán"),
                   ("paramo-volcan","Páramo-Volcán"),("páramo","Páramo"),
                   ("paramo","Páramo"),("cerro","Cerro"),("urbano","Urbano")]:
        if k in tl: datos["nivel_dificultad"] = v2; break

    c = re.search(r'nivel de confort[:\s]+(\d)', tl)
    if c: datos["nivel_confort"] = f"{c.group(1)}/5"

    # Especificaciones
    for pat, key in [
        (r'[Ee]cosistema[:\s]+([^.\n]{10,200})', "ecosistema"),
        (r'[Cc]lima[:\s]+([^.\n]{5,150})',        "clima"),
        (r'[Ee]levaci[oó]n[:\s]+([^.\n]{5,100})', "elevacion"),
        (r'[Uu]bicaci[oó]n[:\s]+([^.\n]{5,200})', "ubicacion"),
        (r'[Dd]istancia[:\s]+([^.\n]{5,100})',    "distancia"),
    ]:
        m = re.search(pat, tx)
        if m: datos[key] = limpiar_texto(m.group(1))

    if re.search(r'bogot[aá]', tl):    datos["ciudad_salida"] = "Bogotá"
    elif re.search(r'medell[ií]n', tl): datos["ciudad_salida"] = "Medellín"

    # Incluye / No incluye
    for pat, key in [
        (r'(?:el precio incluye|incluye)[:\s]+(.*?)(?=no incluye|qué no incluye|precio|fecha|itinerario|$)', 'incluye'),
        (r'(?:no incluye|qué no incluye)[:\s]+(.*?)(?=itinerario|recomendaciones|precio|$)',                 'no_incluye'),
    ]:
        m2 = re.search(pat, hl, re.IGNORECASE | re.DOTALL)
        if m2:
            items = re.findall(r'<li[^>]*>([^<]+)|[-•✓✗]\s*([^\n<]{3,150})', m2.group(1))
            for par in items[:10]:
                i = limpiar_texto(par[0] or par[1])
                if len(i) > 3 and i not in datos[key]:
                    datos[key].append(i)

    # Fechas
    meses = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
             "julio":"07","agosto":"08","septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"}
    fechas = []
    for mes in meses:
        for m3 in re.findall(rf'(\d{{1,2}})\s+(?:de\s+)?{mes}(?:\s+(?:de\s+)?(\d{{4}}))?', tl)[:3]:
            año = m3[1] if m3[1] else "2026"
            f   = f"{m3[0]} de {mes} {año}"
            if f not in fechas: fechas.append(f)
    datos["proximas_fechas"] = fechas[:5]

    # Itinerario
    it = re.search(r'[Ii]tinerario[:\s]+(.*?)(?=[Rr]ecomendaciones|[Ii]ncluye|[Pp]recio|$)', tx, re.DOTALL)
    if it:
        dias = re.findall(r'[Dd][íi]a\s+\d+[:\s]+([^\n]+)', it.group(1)[:1000])
        datos["itinerario"] = [limpiar_texto(d) for d in dias[:7]]

    # Recomendaciones
    reco = re.search(r'[Rr]ecomendaciones[:\s]+((?:[-•]\s*.+\n?){1,})', tx, re.DOTALL)
    if reco:
        items2 = re.findall(r'[-•]\s*(.+?)(?:\n|$)', reco.group(1))
        datos["recomendaciones"] = [limpiar_texto(i) for i in items2[:6] if len(i.strip()) > 3]

    # Cómo inscribirse
    insc = re.search(r'c[oó]mo inscribirse[:\s]+([^.]+\.)', tx, re.IGNORECASE)
    datos["como_inscribirse"] = limpiar_texto(insc.group(1))[:300] if insc else \
        "Escríbenos por WhatsApp +57 300 312 7496 o info@ecoglobalexpeditions.com. Reserva con abono del 50%."

    # PDF
    pdf = re.search(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', hl, re.IGNORECASE)
    if pdf: datos["pdf_url"] = pdf.group(1)

    # Descripción completa
    desc = re.search(r'<(?:p|div)[^>]*>\s*([A-ZÁÉÍÓÚ][^<]{100,500})\s*</(?:p|div)>', hl)
    if desc: datos["descripcion_completa"] = limpiar_texto(desc.group(1))[:500]

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

    # PASO 1: Enriquecimiento
    total = len(expediciones)
    print(f"\n📦 PASO 1 — Enriqueciendo {total} planes...")

    actualizadas = con_precio = con_fechas = 0
    errores = []

    for i, exp in enumerate(expediciones):
        url    = exp.get("url", "")
        nombre = exp.get("nombre", "")
        print(f"  [{i+1}/{total}] {nombre[:55]}...")

        html = await get_html(url)
        if html:
            datos = extraer_datos_plan(html)
            for k, val in datos.items():
                if val is not None and val != [] and val != "":
                    exp[k] = val
            if not exp.get("descripcion") and datos.get("descripcion_completa"):
                exp["descripcion"] = datos["descripcion_completa"]
            actualizadas += 1
            if datos.get("precio_texto"):    con_precio += 1
            if datos.get("proximas_fechas"): con_fechas += 1
            print(f"    ✅ {datos.get('precio_texto','—')} | {len(datos.get('proximas_fechas',[]))} fechas | {len(datos.get('incluye',[]))} incluye")
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
    print(f"   Con fechas:    {con_fechas}")
    if errores: print(f"   Errores:       {errores[:3]}")
    print(f"{'='*55}\n")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(actualizar_catalogo())
