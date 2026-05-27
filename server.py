from fastapi import FastAPI, HTTPException, Header
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

class ScrapeRequest(BaseModel):
    url: str
    pregunta: str = "Extrae toda la información relevante"

class ListarRequest(BaseModel):
    categoria: str = "all"

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
        return "No se pudo obtener información del sitio"

@app.post("/tools/scrape_pagina")
async def scrape_pagina(
    req: ScrapeRequest,
    x_api_key: str = Header(None)
):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="No autorizado")
    try:
        contenido = await crawlear(req.url)
        return {
            "success": True,
            "url": req.url,
            "datos": contenido[:8000],
            "fuente": "ecoglobalexpeditions.com en tiempo real"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "mensaje": "Sitio no disponible. Usa base de conocimiento."
        }

@app.post("/tools/listar_expediciones")
async def listar_expediciones(
    req: ListarRequest,
    x_api_key: str = Header(None)
):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="No autorizado")
    url = URLS.get(req.categoria, URLS["all"])
    try:
        contenido = await crawlear(url)
        return {
            "success": True,
            "categoria": req.categoria,
            "url_consultada": url,
            "expediciones": contenido[:8000]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "servicio": "crawl4ai-bridge-ecoglobal",
        "crawl4ai_conectado": CRAWL4AI_URL
    }
