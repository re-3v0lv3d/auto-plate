"""API HTTP + interfaz web."""

from __future__ import annotations

import base64
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import service, store
from .config import settings
from .normalize import InvalidPlate, SUPPORTED_COUNTRIES, normalize_plate

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Auto-Plate", version="1.0.0", docs_url="/api/docs", redoc_url=None)
PUBLIC_PATHS = {"/api/health", "/api/docs", "/openapi.json"}


def _check_basic(header: str | None) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    user, _, password = decoded.partition(":")
    return secrets.compare_digest(user, settings.api_user) and secrets.compare_digest(
        password, settings.api_password
    )


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    path = request.url.path
    if (
        settings.auth_enabled
        and path.startswith("/api/")
        and path not in PUBLIC_PATHS
        and request.method != "OPTIONS"
        and not _check_basic(request.headers.get("authorization"))
    ):
        # Sin WWW-Authenticate: evita que el navegador abra el diálogo nativo
        # y deja que el frontend gestione el login.
        return JSONResponse({"detail": "Credenciales requeridas"}, status_code=401)
    return await call_next(request)


# Debe añadirse el último para quedar por fuera y añadir cabeceras también a los 401.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

_hits: dict[str, deque[float]] = {}


class LookupRequest(BaseModel):
    plate: str = Field(min_length=1, max_length=20)
    country: str = Field(default="ES", min_length=2, max_length=2)
    captcha_token: str | None = None
    turnstile_token: str | None = None
    refresh: bool = False


def _rate_limited(ip: str) -> bool:
    limit = settings.rate_limit_per_minute
    if limit <= 0:
        return False
    now = time.time()
    bucket = _hits.setdefault(ip, deque(maxlen=limit))
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


@app.on_event("startup")
def _startup() -> None:
    storage = store.get_storage()
    storage.init()
    loaded = storage.seed_if_empty(settings.seed_path)
    if loaded:
        print(f"[seed] importadas {loaded} fichas desde {settings.seed_path}")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "time": time.time()}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "countries": SUPPORTED_COUNTRIES,
        "default_country": "ES",
        "captcha_sitekey": settings.captcha_sitekey,
        "captcha_provider": settings.captcha_provider,
        "pro_api_configured": settings.pro_api_configured,
        "web_provider": settings.allow_web_provider,
        "historialvehiculo_auto": settings.captcha_provider in {"2captcha", "cfsolve"} and settings.captcha_configured,
        "historialvehiculo_sitekey": "0x4AAAAAAA1fwEz8c6iW2gXh",
    }


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    return store.get_storage().stats()


@app.post("/api/lookup")
def lookup(body: LookupRequest, request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "?"
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Demasiadas consultas. Espera un minuto.")

    try:
        outcome = service.lookup(
            body.plate,
            body.country.upper(),
            captcha_token=body.captcha_token,
            turnstile_token=body.turnstile_token,
            refresh=body.refresh,
        )
    except InvalidPlate as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload = outcome.to_dict()
    payload["ok"] = True
    payload["found"] = outcome.vehicle is not None
    return JSONResponse(payload)


class MergeRequest(BaseModel):
    plate: str = Field(min_length=1, max_length=20)
    country: str = Field(default="ES", min_length=2, max_length=2)
    source_url: str = Field(min_length=8)


@app.post("/api/merge")
def merge(body: MergeRequest, request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "?"
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Demasiadas consultas. Espera un minuto.")
    try:
        outcome = service.merge_historial(body.plate, body.country.upper(), body.source_url)
    except InvalidPlate as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - el proveedor ya lanza ProviderError
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    payload = outcome.to_dict()
    payload["ok"] = True
    payload["found"] = outcome.vehicle is not None
    return JSONResponse(payload)


@app.get("/api/vehicle/{plate}")
def vehicle(plate: str, country: str = Query(default="ES", min_length=2, max_length=2)) -> dict[str, Any]:
    try:
        normalized = normalize_plate(plate, country.upper())
    except InvalidPlate as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    found = store.get_storage().get_vehicle(normalized.normalized, normalized.country)
    if not found:
        raise HTTPException(status_code=404, detail="No hay datos para esa matrícula")
    return found.to_dict()
