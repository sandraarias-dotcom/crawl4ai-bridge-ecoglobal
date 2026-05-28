from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import re
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

# ── Scraping directo httpx (sin Playwright, ~1-3 seg) ────────
async def crawlear(url: str) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; EcoBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-CO,es;q=0.9"
            }
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

            # Eliminar bloques no útiles
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            html = re.sub(r'<style[^>]*>.*?</style>',  '', html, flags=re.DOTALL)
            html = re.sub(r'<nav[^>]*>.*?</nav>',      '', html, flags=re.DOTALL)
            html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL)
            html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL)

            # Limpiar tags HTML restantes
            texto = re.sub(r'<[^>]+>', ' ', html)

            # Limpiar espacios múltiples
            texto = re.sub(r'\s+', ' ', texto).strip()

            # Decodificar entidades HTML comunes
            texto = (texto
                .replace('&amp;',   '&')
                .replace('&nbsp;',  ' ')
                .replace('&#8211;', '-')
                .replace('&#8212;', '—')
                .replace('&#8230;', '...')
                .replace('&lt;',    '<')
                .replace('&gt;',    '>')
                .replace('&quot;',  '"')
                .replace('&#039;',  "'")
            )

            return texto[:8000] if texto else "Sin contenido disponible"

    except httpx.TimeoutException:
        return "TIMEOUT: El sitio tardó demasiado. Intenta de nuevo en un momento."
    except httpx.HTTPStatusError as e:
        return f"ERROR HTTP {e.response.status_code}: No se pudo acceder al sitio."
    except Exception as e:
        return f"ERROR: {str(e)}"


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
                            "text": contenido
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
                            "text": contenido
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
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "result": {}
        })

    # ── método no reconocido ─────────────────────────────────
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": jsonrpc_id,
        "error": {
            "code": -32601,
            "message": f"Método '{method}' no reconocido"
        }
    })


# ── Descubrimiento GET ───────────────────────────────────────
@app.get("/mcp")
async def mcp_discovery():
    return {
        "name": "crawl4ai-ecoglobal",
        "version": "1.0.0",
        "description": "Consulta en tiempo real el sitio de Ecoglobal Expeditions",
        "tools": TOOLS
    }


# ── Health check ─────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "servicio": "crawl4ai-bridge-ecoglobal",
        "protocolo": "JSON-RPC 2.0 MCP",
        "motor": "httpx directo (sin Playwright)",
        "crawl4ai_conectado": CRAWL4AI_URL
    }
