"""
cron_actualizar_catalogo.py — Ecoglobal Expeditions
Autodescubre planes nuevos + enriquece todos con datos completos.
Ejecutar: python cron_actualizar_catalogo.py
Railway cron: 0 8 * * * (8AM UTC = 3AM Colombia)
"""

import asyncio
import json
import os
import re
import httpx
from datetime import datetime

CATALOGO_FILE = os.path.join(os.path.dirname(__file__), "catalogo.json")
ALL_URL       = "https://ecoglobalexpeditions.com/all/"
BASE_URL      = "https://ecoglobalexpeditions.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CO,es;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
}


# ── Utilidades ───────────────────────────────────────────────

def cargar_catalogo():
    try:
        with open(CATALOGO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"updated_at": "", "total": 0, "expediciones": []}


def guardar_catalogo(catalogo):
    with open(CATALOGO_FILE, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)


def limpiar_texto(texto: str) -> str:
    texto = re.sub(r'\s+', ' ', texto).strip()
    texto = texto.replace('[:es]','').replace('[:en]','').replace('[:]','')
    return texto


def inferir_categoria(url: str, nombre: str) -> str:
    """Infiere categoría según URL y nombre del plan."""
    u = url.lower()
    n = nombre.lower()
    if any(x in u or x in n for x in ["caminata", "camino", "ascenso", "paramo",
                                        "travesia", "puebliada", "sendero"]):
        return "caminatas"
    if any(x in u or x in n for x in ["expedicion", "safari", "desierto", "tatacoa",
                                        "amazonas", "guajira", "capurgana", "roraima",
                                        "guaviare", "putumayo", "caqueta", "guaviare",
                                        "paramillo", "guanapalo"]):
        return "destinos"
    if any(x in u or x in n for x in ["ballenas", "tortugas", "rafting", "fotografia",
                                        "curso", "avistamiento", "pasadia", "liberacion"]):
        return "actividades"
    return "caminatas"  # default


async def get_html(url: str) -> str:
    """Descarga HTML de una URL."""
    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers=HEADERS
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        print(f"    ⚠️  Error: {e}")
        return ""


# ── PASO 0: Autodescubrimiento de planes nuevos ──────────────

async def descubrir_planes_nuevos(urls_actuales: set) -> list:
    """
    Lee /all/ y detecta URLs nuevas que no están en el catálogo.
    Retorna lista de nuevos planes para agregar.
    """
    print("\n🔍 PASO 0 — Autodescubrimiento de planes nuevos...")
    html = await get_html(ALL_URL)
    if not html:
        print("  ❌ No se pudo acceder a /all/")
        return []

    # Extraer todas las URLs de planes del sitio
    urls_sitio = set(re.findall(
        r'href=["\'](' + re.escape(BASE_URL) + r'/[a-z0-9_-]+/)["\']',
        html
    ))

    # Filtrar solo URLs de planes (excluir secciones del menú)
    excluir = {
        f"{BASE_URL}/caminatas/", f"{BASE_URL}/destinos/",
        f"{BASE_URL}/actividades/", f"{BASE_URL}/contacto/",
        f"{BASE_URL}/preguntanos/", f"{BASE_URL}/all/",
        f"{BASE_URL}/", f"{BASE_URL}/en/",
    }
    urls_planes = urls_sitio - excluir

    # Detectar planes nuevos
    urls_nuevas = urls_planes - urls_actuales
    print(f"  URLs en el sitio:   {len(urls_planes)}")
    print(f"  URLs en catálogo:   {len(urls_actuales)}")
    print(f"  URLs nuevas:        {len(urls_nuevas)}")

    if not urls_nuevas:
        print("  ✅ No hay planes nuevos")
        return []

    # Para cada URL nueva, extraer el nombre desde el HTML del plan
    nuevos_planes = []
    for url in urls_nuevas:
        html_plan = await get_html(url)
        nombre = "Plan sin nombre"
        if html_plan:
            # Extraer el título H1
            h1 = re.search(r'<h1[^>]*>\s*([^<]+)\s*</h1>', html_plan)
            if h1:
                nombre = limpiar_texto(h1.group(1))
            else:
                # Fallback: usar el slug de la URL
                slug = url.rstrip('/').split('/')[-1]
                nombre = slug.replace('-', ' ').replace('_', ' ').title()

        categoria = inferir_categoria(url, nombre)
        nuevo = {
            "id": None,  # Se asigna al guardar
            "nombre": nombre,
            "categoria": categoria,
            "descripcion": "",
            "url": url
        }
        nuevos_planes.append(nuevo)
        print(f"  ➕ Nuevo plan: {nombre[:60]}")
        await asyncio.sleep(0.5)

    return nuevos_planes


# ── PASO 1: Enriquecimiento de datos ─────────────────────────

def extraer_datos_plan(html: str) -> dict:
    """Extrae todos los campos estructurados del HTML de un plan."""
    datos = {
        "precio_desde": None, "precio_texto": None, "precio_vigencia": None,
        "duracion": None, "duracion_dias": None,
        "nivel_dificultad": None, "nivel_confort": None,
        "ecosistema": None, "clima": None, "elevacion": None,
        "ubicacion": None, "distancia": None, "ciudad_salida": None,
        "atractivos": [], "especificaciones": [],
        "proximas_fechas": [],
        "incluye": [], "no_incluye": [],
        "itinerario": [], "recomendaciones": [],
        "como_inscribirse": None, "pdf_url": None,
        "descripcion_completa": None,
    }

    if not html:
        return datos

    html_limpio = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html_limpio = re.sub(r'<style[^>]*>.*?</style>', '', html_limpio, flags=re.DOTALL)
    texto = re.sub(r'<[^>]+>', ' ', html_limpio)
    texto = re.sub(r'\s+', ' ', texto).strip()
    tl    = texto.lower()

    # ── Precio ───────────────────────────────────────────────
    precios = re.findall(r'\$\s*([\d]{1,3}(?:[.,]\d{3})+)', texto)
    if precios:
        ps = precios[0].replace('.','').replace(',','')
        try:
            datos["precio_desde"] = int(ps)
            datos["precio_texto"]  = f"${precios[0]}"
        except:
            datos["precio_texto"]  = f"${precios[0]}"

    v = re.search(r'precio[s]?\s+(?:para\s+el?\s+año\s+)?(\d{4})', tl)
    if v:
        datos["precio_vigencia"] = v.group(1)

    # ── Duración ─────────────────────────────────────────────
    d = re.search(r'(\d+)\s*d[íi]as?\s*(?:y\s*(\d+)\s*noches?)?', tl)
    if d:
        datos["duracion_dias"] = int(d.group(1))
        datos["duracion"] = f"{d.group(1)} días" + (f" y {d.group(2)} noches" if d.group(2) else "")
    elif re.search(r'un d[íi]a|1 d[íi]a|d[íi]a completo', tl):
        datos["duracion_dias"] = 1
        datos["duracion"] = "1 día"

    # ── Dificultad ───────────────────────────────────────────
    for k, v in [("nevado","Nevado"),("páramo-volcán","Páramo-Volcán"),
                  ("paramo-volcan","Páramo-Volcán"),("páramo","Páramo"),
                  ("paramo","Páramo"),("cerro","Cerro"),("urbano","Urbano")]:
        if k in tl:
            datos["nivel_dificultad"] = v
            break

    c = re.search(r'nivel de confort[:\s]+(\d)', tl)
    if c:
        datos["nivel_confort"] = f"{c.group(1)}/5"

    # ── Especificaciones ─────────────────────────────────────
    for campo, key in [
        (r'[Ee]cosistema[:\s]+([^.\n]{10,200})', "ecosistema"),
        (r'[Cc]lima[:\s]+([^.\n]{5,150})',         "clima"),
        (r'[Ee]levaci[oó]n[:\s]+([^.\n]{5,100})',  "elevacion"),
        (r'[Uu]bicaci[oó]n[:\s]+([^.\n]{5,200})',  "ubicacion"),
        (r'[Dd]istancia[:\s]+([^.\n]{5,100})',      "distancia"),
    ]:
        m = re.search(campo, texto)
        if m:
            datos[key] = limpiar_texto(m.group(1))

    # Ciudad de salida
    if re.search(r'bogot[aá]', tl):
        datos["ciudad_salida"] = "Bogotá"
    elif re.search(r'medell[ií]n', tl):
        datos["ciudad_salida"] = "Medellín"

    # ── Atractivos ───────────────────────────────────────────
    at = re.search(
        r'(?:principales?\s+atractivos?|descubre[^:]*:)(.*?)(?:especificaciones|descripci[oó]n|el precio|precio)',
        html_limpio, re.IGNORECASE | re.DOTALL
    )
    if at:
        items = re.findall(r'<li[^>]*>\s*<(?:strong|b|p|span)[^>]*>([^<]+)', at.group(1))
        if not items:
            items = re.findall(r'[-•]\s*([^\n<]{5,150})', at.group(1))
        datos["atractivos"] = [limpiar_texto(i) for i in items[:8] if len(i.strip()) > 3]

    # ── Incluye / No incluye ─────────────────────────────────
    inc = re.search(
        r'(?:el precio incluye|incluye)[:\s]+(.*?)(?=no incluye|qué no incluye|precio|fecha|itinerario|$)',
        html_limpio, re.IGNORECASE | re.DOTALL
    )
    if inc:
        items = re.findall(r'<li[^>]*>([^<]+)|[-•✓]\s*([^\n<]{3,150})', inc.group(1))
        for par in items[:10]:
            i = limpiar_texto(par[0] or par[1])
            if len(i) > 3 and i not in datos["incluye"]:
                datos["incluye"].append(i)

    no_inc = re.search(
        r'(?:no incluye|qué no incluye)[:\s]+(.*?)(?=itinerario|recomendaciones|precio|$)',
        html_limpio, re.IGNORECASE | re.DOTALL
    )
    if no_inc:
        items = re.findall(r'<li[^>]*>([^<]+)|[-•✗]\s*([^\n<]{3,150})', no_inc.group(1))
        for par in items[:8]:
            i = limpiar_texto(par[0] or par[1])
            if len(i) > 3:
                datos["no_incluye"].append(i)

    # ── Fechas ───────────────────────────────────────────────
    meses = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05",
              "junio":"06","julio":"07","agosto":"08","septiembre":"09",
              "octubre":"10","noviembre":"11","diciembre":"12"}
    fechas = []
    for mes, _ in meses.items():
        for m in re.findall(rf'(\d{{1,2}})\s+(?:de\s+)?{mes}(?:\s+(?:de\s+)?(\d{{4}}))?', tl)[:3]:
            año = m[1] if m[1] else "2026"
            f = f"{m[0]} de {mes} {año}"
            if f not in fechas:
                fechas.append(f)
    datos["proximas_fechas"] = fechas[:5]

    # ── Itinerario ───────────────────────────────────────────
    it = re.search(r'[Ii]tinerario[:\s]+(.*?)(?=[Rr]ecomendaciones|[Ii]ncluye|[Pp]recio|$)', texto, re.DOTALL)
    if it:
        dias = re.findall(r'[Dd][íi]a\s+\d+[:\s]+([^\n]+)', it.group(1)[:1000])
        datos["itinerario"] = [limpiar_texto(d) for d in dias[:7]]

    # ── Recomendaciones ──────────────────────────────────────
    reco = re.search(r'[Rr]ecomendaciones[:\s]+((?:[-•]\s*.+\n?){1,})', texto, re.DOTALL)
    if reco:
        items = re.findall(r'[-•]\s*(.+?)(?:\n|$)', reco.group(1))
        datos["recomendaciones"] = [limpiar_texto(i) for i in items[:6] if len(i.strip()) > 3]

    # ── Cómo inscribirse ─────────────────────────────────────
    insc = re.search(r'c[oó]mo inscribirse[:\s]+([^.]+\.)', texto, re.IGNORECASE)
    if insc:
        datos["como_inscribirse"] = limpiar_texto(insc.group(1))[:300]
    else:
        datos["como_inscribirse"] = (
            "Escríbenos por WhatsApp +57 300 312 7496 o a "
            "info@ecoglobalexpeditions.com. Reserva tu cupo con un abono del 50%."
        )

    # ── PDF ──────────────────────────────────────────────────
    pdf = re.search(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html_limpio, re.IGNORECASE)
    if pdf:
        datos["pdf_url"] = pdf.group(1)

    # ── Descripción completa ─────────────────────────────────
    desc = re.search(r'<(?:p|div)[^>]*>\s*([A-ZÁÉÍÓÚ][^<]{100,500})\s*</(?:p|div)>', html_limpio)
    if desc:
        datos["descripcion_completa"] = limpiar_texto(desc.group(1))[:500]

    return datos


# ── PROCESO PRINCIPAL ────────────────────────────────────────

async def actualizar_catalogo():
    inicio = datetime.now()
    print(f"\n{'='*55}")
    print(f"🚀 Actualización catálogo Ecoglobal: {inicio.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}")

    catalogo    = cargar_catalogo()
    expediciones = catalogo.get("expediciones", [])

    # Índice de URLs actuales
    urls_actuales = {exp["url"] for exp in expediciones}

    # ── PASO 0: Autodescubrimiento ───────────────────────────
    nuevos = await descubrir_planes_nuevos(urls_actuales)
    if nuevos:
        # Asignar IDs consecutivos
        max_id = max((e.get("id") or 0 for e in expediciones), default=0)
        for i, nuevo in enumerate(nuevos, 1):
            nuevo["id"] = max_id + i
        expediciones.extend(nuevos)
        print(f"\n  ✅ {len(nuevos)} planes nuevos agregados al catálogo")

    # ── PASO 1: Enriquecimiento ──────────────────────────────
    total = len(expediciones)
    print(f"\n📦 PASO 1 — Enriqueciendo {total} planes con datos del sitio...")

    actualizadas = 0
    con_precio   = 0
    con_fechas   = 0
    errores      = []

    for i, exp in enumerate(expediciones):
        url    = exp.get("url", "")
        nombre = exp.get("nombre", "")
        print(f"  [{i+1}/{total}] {nombre[:55]}...")

        html = await get_html(url)

        if html:
            datos = extraer_datos_plan(html)
            # Actualizar campos — no sobreescribir nombre/categoria/url/id/descripcion base
            for k, v in datos.items():
                if v is not None and v != [] and v != "":
                    exp[k] = v
            # Actualizar descripcion base si no existe
            if not exp.get("descripcion") and datos.get("descripcion_completa"):
                exp["descripcion"] = datos["descripcion_completa"]

            actualizadas += 1
            p = datos.get("precio_texto", "—")
            f = len(datos.get("proximas_fechas", []))
            inc = len(datos.get("incluye", []))
            print(f"    ✅ Precio: {p} | {f} fechas | {inc} items incluye")
            if datos.get("precio_texto"):  con_precio += 1
            if datos.get("proximas_fechas"): con_fechas += 1
        else:
            errores.append(nombre[:40])
            print(f"    ❌ Sin contenido")

        await asyncio.sleep(1.5)

    # ── PASO 2: Guardar ──────────────────────────────────────
    catalogo["updated_at"]   = datetime.now().strftime("%Y-%m-%d %H:%M")
    catalogo["total"]        = len(expediciones)
    catalogo["expediciones"] = expediciones
    guardar_catalogo(catalogo)

    fin = datetime.now()
    seg = (fin - inicio).seconds
    print(f"\n{'='*55}")
    print(f"✅ Catálogo guardado en {seg}s")
    print(f"   Total planes:     {len(expediciones)}")
    print(f"   Actualizadas:     {actualizadas}")
    print(f"   Con precio:       {con_precio}")
    print(f"   Con fechas:       {con_fechas}")
    if errores:
        print(f"   Errores ({len(errores)}):      {errores[:3]}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    asyncio.run(actualizar_catalogo())
