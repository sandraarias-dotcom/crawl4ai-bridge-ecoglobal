from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import json
import os

app = FastAPI()

CATALOGO_FILE = os.path.join(os.path.dirname(__file__), "catalogo.json")

TOOLS = [
    {
        "name": "listar_expediciones",
        "description": "Obtiene el catálogo de expediciones disponibles de Ecoglobal Expeditions. Úsalo cuando el cliente pregunte qué opciones hay según el tipo de naturaleza.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "description": "Filtro: 'caminatas' para montaña/páramo/cerros, 'destinos' para mar/selva/desierto/llanos, 'actividades' para ballenas/rafting/fotografía, 'all' para todo",
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
        "description": "Obtiene el detalle de una expedición específica por nombre.",
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


def buscar_expediciones(categoria: str = "all", busqueda: str = "") -> str:
    catalogo = cargar_catalogo()
    expediciones = catalogo.get("expediciones", [])

    if categoria and categoria != "all":
        expediciones = [e for e in expediciones if e.get("categoria") == categoria]

    if busqueda:
        termino = busqueda.lower()
        expediciones = [
            e for e in expediciones
            if termino in e.get("nombre", "").lower()
            or termino in e.get("descripcion", "").lower()
        ]

    if not expediciones:
        return f"Sin resultados para '{categoria}'."

    total = len(expediciones)
    resultado = f"Planes disponibles ({total} total):\n"
    for exp in expediciones[:10]:
        resultado += f"• {exp['nombre']} — {exp['url']}\n"

    return resultado


def buscar_detalle(nombre: str) -> str:
    catalogo = cargar_catalogo()
    expediciones = catalogo.get("expediciones", [])
    termino = nombre.lower()
    coincidencias = [e for e in expediciones if termino in e.get("nombre", "").lower()]

    if not coincidencias:
        return f"No encontré '{nombre}'."

    exp = coincidencias[0]
    return (
        f"Nombre: {exp['nombre']}\n"
        f"Categoría: {exp['categoria']}\n"
        f"Descripción: {exp['descripcion']}\n"
        f"URL: {exp['url']}\n"
        f"Precios y fechas: WhatsApp +57 300 312 7496"
    )


@app.post("/mcp")
async def mcp_handler(request: Request):
    body = await request.json()
    jsonrpc_id = body.get("id", 1)
    method     = body.get("method", "")
    params     = body.get("params", {})

    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "ecoglobal-catalogo", "version": "2.0.0"},
                "capabilities": {"tools": {}}
            }
        })

    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "result": {"tools": TOOLS}
        })

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "listar_expediciones":
            resultado = buscar_expediciones(
                arguments.get("categoria", "all"),
                arguments.get("busqueda", "")
            )
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": jsonrpc_id,
                "result": {"content": [{"type": "text", "text": resultado}]}
            })

        if tool_name == "detalle_expedicion":
            resultado = buscar_detalle(arguments.get("nombre", ""))
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": jsonrpc_id,
                "result": {"content": [{"type": "text", "text": resultado}]}
            })

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "error": {"code": -32601, "message": f"Tool '{tool_name}' no encontrada"}
        })

    if method.startswith("notifications/"):
        return JSONResponse({"jsonrpc": "2.0", "id": jsonrpc_id, "result": {}})

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": jsonrpc_id,
        "error": {"code": -32601, "message": f"Método '{method}' no reconocido"}
    })


@app.get("/mcp")
async def mcp_discovery():
    catalogo = cargar_catalogo()
    return {
        "name": "ecoglobal-catalogo",
        "version": "2.0.0",
        "description": "Catálogo Ecoglobal Expeditions — 64 planes",
        "total_planes": catalogo.get("total", 0),
        "tools": TOOLS
    }


@app.get("/health")
async def health():
    catalogo = cargar_catalogo()
    return {
        "status": "ok",
        "servicio": "ecoglobal-catalogo-mcp",
        "motor": "JSON estático (sin scraping)",
        "total_planes": catalogo.get("total", 0),
        "updated_at": catalogo.get("updated_at", "")
    }
