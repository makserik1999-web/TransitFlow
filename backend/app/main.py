"""Точка входа FastAPI. На Этапе 0 — health + auth. Раздача статики фронта — Этап 1."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.routers import auth as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create_all на старте (без Alembic, раздел 9). Идемпотентно.
    init_db()
    yield


app = FastAPI(
    title="TransitFlow Mangystau API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth_router.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "transitflow"}
