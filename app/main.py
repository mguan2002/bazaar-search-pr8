"""Bazaar Search & Discovery — standalone FastAPI app (P3 vertical slice).

At merge time this whole module is replaced by S2's service; only `routes_listings.router`
moves over (via `include_router`). Error-envelope handlers below mirror §3.6.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.routes_listings import router as listings_router

app = FastAPI(
    title="Bazaar Search & Discovery API",
    version="0.1.0",
    description="P3 standalone slice — browse + full-text search over listings.",
)
app.include_router(listings_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    # §3.6 uses a flat {"error": "..."} envelope instead of FastAPI's {"detail": ...}.
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {"msg": "invalid request"}
    loc = ".".join(str(p) for p in first.get("loc", []) if p != "query")
    msg = first.get("msg", "invalid request")
    return JSONResponse(
        status_code=422, content={"error": f"{loc}: {msg}" if loc else msg}
    )


@app.exception_handler(DBAPIError)
async def db_error_handler(_: Request, exc: DBAPIError) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"error": "search temporarily unavailable"}
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
