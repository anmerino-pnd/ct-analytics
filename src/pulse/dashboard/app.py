"""FastAPI app del dashboard: rutas y arranque.

Sirve 7 vistas HTML bajo `/dashboard/<vista>` y un API JSON bajo `/api/...`.
La raíz redirige a `/dashboard/overview`. Los static (CSS/JS) se sirven desde
`/static`. La conexión DuckDB se calienta en el `startup` para que la primera
petición no pague el costo del registro de vistas.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from pulse.dashboard.db import get_connection
from pulse.dashboard.routers import api, pages

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("pulse.dashboard")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("Calentando conexión DuckDB y registrando vistas...")
    get_connection()
    log.info("Dashboard listo")
    yield


app = FastAPI(title="Pulse Dashboard", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(pages.router, prefix="/dashboard")
app.include_router(api.router, prefix="/api")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard/overview")
