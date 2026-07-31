"""Search & browse endpoints (design doc §3.2) + validation/errors (§3.6).

GET /v1/listings         — browse (recency-first, geo/category/price filters)
GET /v1/listings/search  — full-text search (relevance-first)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_app_id
from app.models import CATEGORIES, Condition
from app.schemas import ListingResponse, ListingsPage, Pagination
from app.search import (
    SORT_NEWEST,
    SORT_PRICE_ASC,
    SORT_PRICE_DESC,
    SORT_RELEVANCE,
    ListingFilters,
    count_results,
    run_query,
)

router = APIRouter(prefix="/v1/listings", tags=["listings"])

_CONDITIONS = {c.value for c in Condition}
_BROWSE_SORTS = {SORT_NEWEST, SORT_PRICE_ASC, SORT_PRICE_DESC}
_SEARCH_SORTS = {SORT_RELEVANCE, SORT_PRICE_ASC, SORT_PRICE_DESC}


def _build_filters(
    *,
    app_id: str,
    q: str | None,
    latitude: float | None,
    longitude: float | None,
    radius_km: float,
    category: str | None,
    condition: str | None,
    price_min_cents: int | None,
    price_max_cents: int | None,
    sort: str,
    limit: int,
    offset: int,
) -> ListingFilters:
    """Validate query params per §3.6 and return ListingFilters (or raise HTTPException)."""
    if not 0 < radius_km <= 100:
        raise HTTPException(422, "radius_km must be between 0 and 100")
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            422, "both latitude and longitude are required for geo filtering"
        )
    if category is not None and category not in CATEGORIES:
        raise HTTPException(
            422, f"invalid category. Valid values: {sorted(CATEGORIES)}"
        )
    if condition is not None and condition not in _CONDITIONS:
        raise HTTPException(
            422, f"invalid condition. Valid values: {sorted(_CONDITIONS)}"
        )
    allowed_sorts = _SEARCH_SORTS if q else _BROWSE_SORTS
    if sort not in allowed_sorts:
        raise HTTPException(
            422, f"invalid sort. Valid values: {sorted(allowed_sorts)}"
        )
    return ListingFilters(
        app_id=app_id,
        q=q,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        category=category,
        condition=condition,
        price_min_cents=price_min_cents,
        price_max_cents=price_max_cents,
        sort=sort,
        limit=limit,
        offset=offset,
    )


def _page(session: Session, f: ListingFilters) -> ListingsPage:
    total = count_results(session, f)
    rows = run_query(session, f)
    return ListingsPage(
        data=[ListingResponse.from_listing(r) for r in rows],
        pagination=Pagination(
            total=total,
            limit=f.limit,
            offset=f.offset,
            has_more=f.offset + len(rows) < total,
        ),
    )


@router.get("", response_model=ListingsPage)
def browse(
    app_id: str = Depends(get_app_id),
    session: Session = Depends(get_session),
    latitude: float | None = Query(default=None),
    longitude: float | None = Query(default=None),
    radius_km: float = Query(default=25.0),
    category: str | None = Query(default=None),
    condition: str | None = Query(default=None),
    price_min_cents: int | None = Query(default=None, ge=0),
    price_max_cents: int | None = Query(default=None, ge=0),
    sort: str = Query(default=SORT_NEWEST),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> ListingsPage:
    f = _build_filters(
        app_id=app_id,
        q=None,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        category=category,
        condition=condition,
        price_min_cents=price_min_cents,
        price_max_cents=price_max_cents,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return _page(session, f)


@router.get("/search", response_model=ListingsPage)
def search(
    app_id: str = Depends(get_app_id),
    session: Session = Depends(get_session),
    # q is declared optional so we can return the documented 400 (not FastAPI's 422)
    # when it is missing or blank (§3.6).
    q: str | None = Query(default=None, max_length=200),
    latitude: float | None = Query(default=None),
    longitude: float | None = Query(default=None),
    radius_km: float = Query(default=25.0),
    category: str | None = Query(default=None),
    condition: str | None = Query(default=None),
    price_min_cents: int | None = Query(default=None, ge=0),
    price_max_cents: int | None = Query(default=None, ge=0),
    sort: str = Query(default=SORT_RELEVANCE),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> ListingsPage:
    if q is None or not q.strip():
        raise HTTPException(400, "query parameter 'q' is required")
    f = _build_filters(
        app_id=app_id,
        q=q,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        category=category,
        condition=condition,
        price_min_cents=price_min_cents,
        price_max_cents=price_max_cents,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return _page(session, f)
