"""Browse + full-text search query builders (design doc §3.3, §3.4).

Ranking is deliberately simple and orthogonal (§3.4):
  - browse  → newest first (created_at DESC)
  - search  → text relevance (ts_rank), tie-broken by created_at DESC
Geo is always a *filter* (bounding box), never a sort.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, and_, desc, func, select
from sqlalchemy.orm import Session

from app.geo import bounding_box
from app.models import Listing, ListingStatus

SORT_NEWEST = "newest"
SORT_PRICE_ASC = "price_asc"
SORT_PRICE_DESC = "price_desc"
SORT_RELEVANCE = "relevance"


@dataclass
class ListingFilters:
    """Common filters for both browse and search. `app_id` is injected by auth (never a
    client param, §3.2). `q` present ⇒ full-text search path."""

    app_id: str
    q: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float = 25.0
    category: str | None = None
    condition: str | None = None
    price_min_cents: int | None = None
    price_max_cents: int | None = None
    sort: str = SORT_NEWEST
    limit: int = 20
    offset: int = 0


def _apply_common_filters(stmt: Select, f: ListingFilters) -> Select:
    stmt = stmt.where(
        Listing.app_id == f.app_id,
        Listing.status == ListingStatus.active.value,
    )
    if f.category is not None:
        stmt = stmt.where(Listing.category == f.category)
    if f.condition is not None:
        stmt = stmt.where(Listing.condition == f.condition)
    if f.price_min_cents is not None:
        stmt = stmt.where(Listing.price_cents >= f.price_min_cents)
    if f.price_max_cents is not None:
        stmt = stmt.where(Listing.price_cents <= f.price_max_cents)
    if f.latitude is not None and f.longitude is not None:
        box = bounding_box(f.latitude, f.longitude, f.radius_km)
        stmt = stmt.where(
            and_(
                Listing.latitude.between(box.south, box.north),
                Listing.longitude.between(box.west, box.east),
            )
        )
    return stmt


def _browse_order(stmt: Select, sort: str) -> Select:
    if sort == SORT_PRICE_ASC:
        return stmt.order_by(Listing.price_cents.asc(), Listing.created_at.desc())
    if sort == SORT_PRICE_DESC:
        return stmt.order_by(Listing.price_cents.desc(), Listing.created_at.desc())
    return stmt.order_by(Listing.created_at.desc())  # newest (default)


def _tsquery(q: str):
    return func.plainto_tsquery("english", q)


def count_results(session: Session, f: ListingFilters) -> int:
    stmt = select(func.count()).select_from(Listing)
    stmt = _apply_common_filters(stmt, f)
    if f.q:
        stmt = stmt.where(Listing.search_vector.op("@@")(_tsquery(f.q)))
    return session.execute(stmt).scalar_one()


def run_query(session: Session, f: ListingFilters) -> list[Listing]:
    """Return the page of listings for `f` (browse when q is None, else full-text search)."""
    if f.q:
        query = _tsquery(f.q)
        relevance = func.ts_rank(Listing.search_vector, query).label("relevance")
        stmt = select(Listing).where(Listing.search_vector.op("@@")(query))
        stmt = _apply_common_filters(stmt, f)
        if f.sort in (SORT_PRICE_ASC, SORT_PRICE_DESC):
            stmt = _browse_order(stmt, f.sort)
        else:  # relevance (default for search) — tie-break by recency
            stmt = stmt.order_by(desc(relevance), Listing.created_at.desc())
    else:
        stmt = select(Listing)
        stmt = _apply_common_filters(stmt, f)
        stmt = _browse_order(stmt, f.sort)

    stmt = stmt.limit(f.limit).offset(f.offset)
    return list(session.execute(stmt).scalars().all())
