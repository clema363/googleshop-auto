from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
from workflow import run_workflow_result

app = FastAPI(title="facture-flow prospection")


class ScrapeRequest(BaseModel):
    query: str


@app.get("/")
def root():
    return {"status": "ok", "message": "facture-flow prospection API"}


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query est requis")
    try:
        results = await run_workflow_result(req.query)
        return {"query": req.query, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
