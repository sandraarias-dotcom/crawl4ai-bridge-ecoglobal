from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import json
import os

app = FastAPI()
CATALOGO_FILE = os.path.join(os.path.dirname(__file__), "catalogo.json")

TOOLS = [
    {
        "name": "listar_expediciones",
        "description": "Obtiene el catálogo de expediciones de Ecoglobal con precios, fechas y detalles. Úsalo siempre que el cliente pregunte qué opciones hay según tipo de naturaleza.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "description": "Filtro: 'caminatas' montaña/páramo/cerros/cascadas, 'destinos' mar/selva/desierto/llanos, 'actividades' ballenas/rafting/fotografía, 'all' todo",
                    "default": "all"
                },
                "busqueda": {
                    "type": "string",
                    "description": "Término opcional para filtrar por nombre o descripción"
                }
            }
        }
    },
    {
        "name": "detalle_expedicion",
        "description": "Obtiene TODOS los detalles de una expedición: precio, fechas, incluye, no incluye, itinerario, recomendaciones. Úsalo cuando el cliente quiera profundizar en un plan específico.",
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


def cargar_catalogo():
    try:
        with open(CATALOGO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e), "expediciones": []}


def resumen_plan(exp: dict) -> str:
    """Formato compacto para listado — máximo 5 líneas por plan."""
    lineas = [f"• {exp['nombre']}"]
    if exp.get("precio_texto"):
        lineas.append(f"  Precio: {exp['precio_texto']} p/persona")
    if exp.get("duracion"):
        lineas.append(f"  Duración: {exp['duracion']}")
    if exp.get("nivel_dificultad"):
        lineas.append(f"  Dificultad: {exp['nivel_dificultad']}")
    if exp.get("proximas_fechas"):
        fechas = ", ".join(exp["proximas_fechas"][:2])
        lineas.append(f"  Próx. salidas: {fechas}")
    lineas.append(f"  URL: {exp['url']}")
    return "\n".join(lineas)


def detalle_plan(exp: dict) -> str:
    """Formato completo para detalle de un plan específico."""
    nd = "No disponible — consultar con asesor"
    lineas = [
        f"PLAN: {exp['nombre']}",
        f"Descripción: {exp.get('descripcion', nd)}",
        "",
        f"PRECIO: {exp.get('precio_texto', nd)} por persona",
    ]
    if exp.get("precio_vigencia"):
        lineas.append(f"Vigencia precio: {exp['precio_vigencia']}")

    lineas += [
        f"Duración: {exp.get('duracion', nd)}",
        f"Dificultad: {exp.get('nivel_dificultad', nd)}",
        f"Nivel confort: {exp.get('nivel_confort', nd)}",
    ]

    if exp.get("ubicacion"):
        lineas.append(f"Ubicación: {exp['ubicacion']}")
    if exp.get("ecosistema"):
        lineas.append(f"Ecosistema: {exp['ecosistema']}")
    if exp.get("clima"):
        lineas.append(f"Clima: {exp['clima']}")
    if exp.get("ciudad_salida"):
        lineas.append(f"Sale desde: {exp['ciudad_salida']}")

    if exp.get("proximas_fechas"):
        lineas += ["", f"FECHAS DISPONIBLES:"]
        for f in exp["proximas_fechas"][:5]:
            lineas.append(f"  - {f}")
    else:
        lineas.append(f"\nFECHAS: {nd}")

    if exp.get("atractivos"):
        lineas += ["", "ATRACTIVOS PRINCIPALES:"]
        for a in exp["atractivos"][:5]:
            lineas.append(f"  - {a}")

    if exp.get("incluye"):
        lineas += ["", "INCLUYE:"]
        for i in exp["incluye"][:6]:
            lineas.append(f"  - {i}")
    else:
        lineas.append(f"\nINCLUYE: {nd}")

    if exp.get("no_incluye"):
        lineas += ["", "NO INCLUYE:"]
        for i in exp["no_incluye"][:5]:
            lineas.append(f"  - {i}")

    if exp.get("itinerario"):
        lineas += ["", "ITINERARIO:"]
        for it in exp["itinerario"][:5]:
            lineas.append(f"  {it}")

    if exp.get("recomendaciones"):
        lineas += ["", "RECOMENDACIONES:"]
        for r in exp["recomendaciones"][:4]:
            lineas.append(f"  - {r}")

    lineas += [
        "",
        f"CÓMO INSCRIBIRSE: {exp.get('como_inscribirse', nd)}",
        f"URL: {exp['url']}",
    ]
    if exp.get("pdf_url"):
        lineas.append(f"PDF info: {exp['pdf_url']}")

    return "\n".join(lineas)


def buscar_expediciones(categoria: str = "all", busqueda: str = "") -> str:
    catalogo = cargar_catalogo()
    exps = catalogo.get("expediciones", [])

    if categoria and categoria != "all":
        exps = [e for e in exps if e.get("categoria") == categoria]

    if busqueda:
        t = busqueda.lower()
        exps = [e for e in exps if t in e.get("nombre","").lower()
                or t in e.get("descripcion","").lower()]

    if not exps:
        return f"Sin resultados para '{categoria}'."

    total = len(exps)
    resultado = f"Planes disponibles ({total} total, mostrando 8):\n\n"
    for exp in exps[:8]:
        resultado += resumen_plan(exp) + "\n\n"
    return resultado.strip()


def buscar_detalle(nombre: str) -> str:
    catalogo = cargar_catalogo()
    exps = catalogo.get("expediciones", [])
    t = nombre.lower()
    coincidencias = [e for e in exps if t in e.get("nombre","").lower()]

    if not coincidencias:
        return f"No encontré '{nombre}'. Prueba con otro término."

    return detalle_plan(coincidencias[0])


# ── MCP JSON-RPC 2.0 ─────────────────────────────────────────
@app.post("/mcp")
async def mcp_handler(request: Request):
    body       = await request.json()
    rid        = body.get("id", 1)
    method     = body.get("method", "")
    params     = body.get("params", {})

    if method == "initialize":
        return JSONResponse({"jsonrpc":"2.0","id":rid,"result":{
            "protocolVersion":"2024-11-05",
            "serverInfo":{"name":"ecoglobal-catalogo","version":"3.0.0"},
            "capabilities":{"tools":{}}
        }})

    if method == "tools/list":
        return JSONResponse({"jsonrpc":"2.0","id":rid,"result":{"tools":TOOLS}})

    if method == "tools/call":
        tn   = params.get("name","")
        args = params.get("arguments",{})

        if tn == "listar_expediciones":
            r = buscar_expediciones(args.get("categoria","all"), args.get("busqueda",""))
        elif tn == "detalle_expedicion":
            r = buscar_detalle(args.get("nombre",""))
        else:
            return JSONResponse({"jsonrpc":"2.0","id":rid,
                "error":{"code":-32601,"message":f"Tool '{tn}' no encontrada"}})

        return JSONResponse({"jsonrpc":"2.0","id":rid,
            "result":{"content":[{"type":"text","text":r}]}})

    if method.startswith("notifications/"):
        return JSONResponse({"jsonrpc":"2.0","id":rid,"result":{}})

    return JSONResponse({"jsonrpc":"2.0","id":rid,
        "error":{"code":-32601,"message":f"Método '{method}' no reconocido"}})


# ── Trigger manual del cron ──────────────────────────────────
@app.post("/admin/actualizar-catalogo")
async def trigger_cron(background_tasks: BackgroundTasks):
    async def run():
        try:
            from cron_actualizar_catalogo import actualizar_catalogo
            await actualizar_catalogo()
        except Exception as e:
            print(f"Error cron: {e}")
    background_tasks.add_task(run)
    return {"status": "Actualización iniciada en background — revisa los logs"}


@app.get("/mcp")
async def mcp_discovery():
    c = cargar_catalogo()
    return {"name":"ecoglobal-catalogo","version":"3.0.0",
            "total_planes":c.get("total",0),"updated_at":c.get("updated_at",""),"tools":TOOLS}


@app.get("/health")
async def health():
    c    = cargar_catalogo()
    exps = c.get("expediciones",[])
    return {
        "status": "ok",
        "version": "3.0.0",
        "total_planes": c.get("total", 0),
        "planes_con_precio": sum(1 for e in exps if e.get("precio_texto")),
        "planes_con_fechas": sum(1 for e in exps if e.get("proximas_fechas")),
        "planes_con_incluye": sum(1 for e in exps if e.get("incluye")),
        "updated_at": c.get("updated_at", "")
    }
