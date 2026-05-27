from fastapi import FastAPI, HTTPException, Header, Request
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

# ── MCP: descubrimiento de herramientas ──────────────────────
@app.get("/mcp")
async def mcp_info():
    return {
        "name": "crawl4ai-ecoglobal",
        "version": "1.0.0",
        "description": "Consulta en tiempo real el sitio de Ecoglobal Expeditions",
        "tools": [
            {
                "name": "scrape_pagina",
                "description": "Consulta una URL del sitio ecoglobalexpeditions.com y extrae su contenido actualizado. Úsalo cuando el cliente pregunte por expediciones específicas, precios o fechas.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL a consultar, ej: https://ecoglobalexpeditions.com/caminatas/"
                        },
                        "pregunta": {
                            "type": "string",
                            "description": "Qué información extraer"
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
    }

# ── MCP: ejecución de herramientas (endpoint principal) ──────
@app.post("/mcp")
async def mcp_execute(request: Request):
    body = await request.json()
    tool_name = body.get("tool")
    params    = body.get("parameters", {})

    if tool_name == "scrape_pagina":
        url = params.get("url", URLS["all"])
        try:
            contenido = await crawlear(url)
            return {"result": contenido[:8000], "fuente": url}
        except Exception as e:
            return {"error": str(e), "result": "No se pudo consultar el sitio"}

    elif tool_name == "listar_expediciones":
        categoria = params.get("categoria", "all")
        url = URLS.get(categoria, URLS["all"])
        try:
            contenido = await crawlear(url)
            return {"result": contenido[:8000], "url_consultada": url}
        except Exception as e:
            return {"error": str(e)}

    else:
        raise HTTPException(status_code=400, detail=f"Tool '{tool_name}' no existe")

# ── Función core de crawling ─────────────────────────────────
async def crawlear(url: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{CRAWL4AI_URL}/crawl",
            headers={"Authorization": f"Bearer {CRAWL4AI_TOKEN}"},
            json={
                "urls": [url],
                "word_count_threshold": 5,
                "bypass_cache": True,
                "crawler_params": {
                    "headless": True,
                    "page_timeout": 30000
                }
            }
        )
        data = resp.json()
        if data.get("results") and len(data["results"]) > 0:
            return data["results"][0].get("markdown", "Sin contenido")
        return "No se pudo obtener información"

# ── Endpoints REST legacy (siguen funcionando) ───────────────
class ScrapeRequest(BaseModel):
    url: str
    pregunta: str = "Extrae toda la información relevante"

class ListarRequest(BaseModel):
    categoria: str = "all"

@app.post("/tools/scrape_pagina")
async def scrape_pagina(req: ScrapeRequest, x_api_key: str = Header(None)):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="No autorizado")
    try:
        contenido = await crawlear(req.url)
        return {"success": True, "datos": contenido[:8000]}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/tools/listar_expediciones")
async def listar_expediciones(req: ListarRequest, x_api_key: str = Header(None)):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="No autorizado")
    url = URLS.get(req.categoria, URLS["all"])
    try:
        contenido = await crawlear(url)
        return {"success": True, "expediciones": contenido[:8000]}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "servicio": "crawl4ai-bridge-ecoglobal",
        "crawl4ai_conectado": CRAWL4AI_URL
    }
