"""Bazaar Search & Discovery — standalone FastAPI app (P3 vertical slice).

At merge time this whole module is replaced by S2's service; only routes_listings.router
moves over (via include_router). Error-envelope handlers mirror S2 middleware T283279748:
  {error:{code,message,request_id}}

PR8 contract delta: unified GET /v1/listings, unit=km|mi, distance_km, seller/status filters.
"""

from __future__ import annotations

import pathlib

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.middleware.request_context import current_request_id
from app.middleware.request_id import RequestIdMiddleware
from app.routes_listings import ApiError, router as listings_router

VALIDATION_FAILED = "validation_failed"


def _envelope(code: str, message: str) -> dict:
    return {
        "error": {"code": code, "message": message, "request_id": current_request_id()}
    }


app = FastAPI(
    title="Bazaar Search & Discovery API",
    version="0.2.0",
    description="P3 standalone slice — browse + full-text unified GET /v1/listings (PR8).",
)
# Outermost so every response (including 401 if auth were added) carries X-Request-Id
app.add_middleware(RequestIdMiddleware)
app.include_router(listings_router)

_STATIC_DIR = pathlib.Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content=_envelope(exc.code, exc.message)
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    # Map Starlette HTTPExceptions (e.g. 405, 404) to envelope
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    # Heuristic code mapping per bazaar-p3 errors.py
    status_to_code = {
        400: VALIDATION_FAILED,
        401: "unauthenticated",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        429: "rate_limited",
    }
    code = status_to_code.get(exc.status_code, "error")
    return JSONResponse(
        status_code=exc.status_code, content=_envelope(code, detail or code)
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    # Per S2 middleware, framework validation errors become 400 validation_failed, not 422
    first = exc.errors()[0] if exc.errors() else {"loc": (), "msg": "invalid request"}
    loc = ".".join(
        str(p) for p in first.get("loc", []) if p not in ("query", "path", "body")
    )
    msg = first.get("msg", "invalid request")
    message = f"{loc}: {msg}" if loc else msg
    return JSONResponse(status_code=400, content=_envelope(VALIDATION_FAILED, message))


@app.exception_handler(DBAPIError)
async def db_error_handler(_: Request, exc: DBAPIError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=_envelope("search_unavailable", "search temporarily unavailable"),
    )


@app.get("/health")
@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}
