from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import load_config
from src.query.generate import answer_question, list_stage_files
from src.query.retrieve import _model

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg = load_config()
    _model(cfg["embedding_model"])
    yield


app = FastAPI(title="HDFC MF FAQ assistant", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class AskBody(BaseModel):
    question: str = Field(min_length=0, max_length=500)


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.post("/ask")
def ask(body: AskBody):
    try:
        return answer_question(body.question)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not answer right now.") from exc


@app.get("/stages")
def stages():
    return list_stage_files()
