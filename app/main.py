"""
FastAPI entrypoint for the Smart Payment Failure Analyzer.

Endpoints:
  GET  /                -> serves the frontend dashboard
  POST /api/analyze      -> upload a CSV, get back summary + insights (+ optional AI narrative)
  GET  /api/sample       -> analyze the bundled sample dataset (no upload needed, good for demos)

Run locally:
  uvicorn app.main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import llm
from .analyzer import compute_summary, generate_insights, load_csv

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_CSV = BASE_DIR / "data" / "sample_transactions.csv"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="Smart Payment Failure Analyzer", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _build_response(csv_bytes: bytes) -> dict:
    try:
        df = load_csv(csv_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    summary = compute_summary(df)
    insights = generate_insights(summary)

    ai_summary = None
    ai_error = None
    if llm.is_available():
        try:
            ai_summary = llm.summarize_insights(summary, insights)
        except Exception as e:  # noqa: BLE001
            ai_error = str(e)

    return {
        "summary": summary,
        "insights": insights,
        "ai_summary": ai_summary,
        "ai_summary_error": ai_error,
        "ai_available": llm.is_available(),
    }


@app.get("/")
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file")
    content = await file.read()
    return _build_response(content)


@app.get("/api/sample")
def analyze_sample():
    content = SAMPLE_CSV.read_bytes()
    return _build_response(content)


@app.get("/api/health")
def health():
    return {"status": "ok"}
