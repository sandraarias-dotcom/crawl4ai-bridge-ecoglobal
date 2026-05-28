from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx
import os

app = FastAPI()

CRAWL4AI_URL   = os.getenv("CRAWL4AI_URL")
CRAWL4AI_TOKEN = os.getenv("CRAWL4AI_TOKEN")
API_SECRET     = os.getenv("API_SECRET")

URLS = {
    "all":         "https://ecoglobalexpeditions.com/all/",
    "caminatas":   "https://ecoglobalexpeditions.com/caminatas/",
    "destinos":    "https://ecoglobalexpeditions.com/destinos/",
    "actividades": "https://ecoglobalexpeditions.com/actividades/",
}

TOOLS = [
    {
        "name": "scrape_pagina",
        "description": "Consulta una URL del sitio ecoglobalexpeditions.com y extrae su contenido actualizado en tiempo real. Úsalo cuando el cliente pregunte por expediciones específicas, precios o fechas.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL a consultar. Ej: https://ecoglobalexpeditions.com/caminatas/"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "listar_expediciones",
        "description": "Obtiene el catálogo completo de expediciones disponibles desde el sitio web en tiempo real.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "description": "Filtro: caminatas, destinos, actividades, o all",
                    "default": "all"
                }
            }
        }
    }
]

async def crawlear(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                f"{CRAWL4AI_URL}/crawl",
                headers={"Authorization": f"Bearer {CRAWL4AI_TOKEN}"},
                json={
                    "urls": [url],
                    "word_count_threshold": 5,
                    "bypass_cache": True,
                    "crawler_params": {
                        "headless": True,
                        "page_timeout": 20000,
                        "wait_for": "domcontentloaded"
                    },
                    "content_filter": {
                        "type": "PruningContentFilter",
                        "threshold": 0.4
                    }
                }                
            )
            data = resp.json()
            if data.get("results") and len(data["results"]) > 0:
                return data["results"][0].get("markdown", "Sin contenido")
            return "No se pudo obtener información del sitio"
    except Exception as e:
        return f"Error al consultar el sitio: {str(e)}"

# ── Endpoint principal MCP (JSON-RPC 2.0) ───────────────────
@app.post("/mcp")
async def mcp_handler(request: Request):
    body = await request.json()

    jsonrpc_id = body.get("id", 1)
    method     = body.get("method", "")
    params     = body.get("params", {})

    # ── initialize ───────────────────────────────────────────
    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "crawl4ai-ecoglobal",
                    "version": "1.0.0"
                },
                "capabilities": {
                    "tools": {}
                }
            }
        })

    # ── tools/list ───────────────────────────────────────────
    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "result": {
                "tools": TOOLS
            }
        })

    # ── tools/call ───────────────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "scrape_pagina":
            url = arguments.get("url", URLS["all"])
            contenido = await crawlear(url)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": jsonrpc_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": contenido[:8000]
                        }
                    ]
                }
            })

        if tool_name == "listar_expediciones":
            categoria = arguments.get("categoria", "all")
            url = URLS.get(categoria, URLS["all"])
            contenido = await crawlear(url)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": jsonrpc_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": contenido[:8000]
                        }
                    ]
                }
            })

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "error": {
                "code": -32601,
                "message": f"Tool '{tool_name}' no encontrada"
            }
        })

    # ── notifications (no requieren respuesta) ───────────────
    if method.startswith("notifications/"):
        return JSONResponse({"jsonrpc": "2.0", "id": jsonrpc_id, "result": {}})

    # ── método no reconocido ─────────────────────────────────
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": jsonrpc_id,
        "error": {
            "code": -32601,
            "message": f"Método '{method}' no reconocido"
        }
    })

# ── Descubrimiento GET (algunos clientes lo usan) ────────────
@app.get("/mcp")
async def mcp_discovery():
    return {
        "name": "crawl4ai-ecoglobal",
        "version": "1.0.0",
        "description": "Consulta en tiempo real el sitio de Ecoglobal Expeditions",
        "tools": TOOLS
    }

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "servicio": "crawl4ai-bridge-ecoglobal",
        "protocolo": "JSON-RPC 2.0 MCP",
        "crawl4ai_conectado": CRAWL4AI_URL
    }
