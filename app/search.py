"""Browse + full-text query builders (design doc §3.3, §3.4, T282737868).

Unified endpoint GET /v1/listings — browse when q absent, search when q present.
Ranking is orthogonal (TDD §3.4):
 - browse → newest first (created_at DESC, id DESC total order)
 - search → ts_rank relevance, tie-broken by created_at DESC
Geo is always a *filter* (bounding box + haversine exact), never a sort.
Distance_km is projected when geo params present.

Structure mirrors bazaar-p3/apps/api/src/bazaar_api/modules/listings/query.py but
sync SQLAlchemy for the standalone slice.

Two invariants from reference:
- Tenant scoping via app_id WHERE (slice stub; real repo uses RLS policy)
- pagination.total = count with identical filters, or has_more lies
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ColumnElement, Select, and_, desc, func, select
from sqlalchemy.orm import Session

from app.geo import RadiusUnit, bounding_box, haversine_km, to_km
from app.models import Listing, ListingStatus

SORT_NEWEST = "newest"
SORT_PRICE_ASC = "price_asc"
SORT_PRICE_DESC = "price_desc"
SORT_RELEVANCE = "relevance"

VALID_SORTS_BROWSE = {SORT_NEWEST, SORT_PRICE_ASC, SORT_PRICE_DESC}
VALID_SORTS_SEARCH = {SORT_RELEVANCE, SORT_PRICE_ASC, SORT_PRICE_DESC, SORT_NEWEST}
# Per spec: relevance only valid when q present; newest is browse default but allowed in search as explicit override
# We'll validate in route layer; builder accepts any.

DEFAULT_STATUS = ListingStatus.active.value
FTS_CONFIG = "english"
_EARTH_RADIUS_KM = 6371.0


@dataclass
class GeoFilter:
    """Resolved geo filter after unit conversion. radius_km is post-conversion."""

    lat: float
    lng: float
    radius_km: float

    def __post_init__(self) -> None:
        if not (
            math.isfinite(self.lat)
            and math.isfinite(self.lng)
            and math.isfinite(self.radius_km)
        ):
            raise ValueError("geo filter must be finite")
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"lat {self.lat} out of range [-90, 90]")
        if not (-180.0 <= self.lng <= 180.0):
            raise ValueError(f"lng {self.lng} out of range [-180, 180]")
        if not (0 < self.radius_km <= 100):
            raise ValueError(f"radius_km {self.radius_km} must be in (0, 100]")


@dataclass
class ListingFilters:
    """Common filters for browse/search. app_id injected by auth (never client param)."""

    app_id: str
    q: str | None = None
    geo: GeoFilter | None = None
    category: str | None = None
    condition: str | None = None
    price_min_cents: int | None = None
    price_max_cents: int | None = None
    seller_user_id: str | None = None
    status: str | None = None  # single-value; defaults to active in WHERE builder
    sort: str = SORT_NEWEST
    limit: int = 20
    offset: int = 0

    # legacy fields kept for slice compat during migration — constructed from geo
    @property
    def latitude(self) -> float | None:
        return self.geo.lat if self.geo else None

    @property
    def longitude(self) -> float | None:
        return self.geo.lng if self.geo else None

    @property
    def radius_km(self) -> float:
        return self.geo.radius_km if self.geo else 25.0


def _distance_expr(geo: GeoFilter) -> ColumnElement[float]:
    """Haversine great-circle distance (km) as SQLAlchemy expression.

    Mirrors geo.haversine_km() Python reference. Used both in SELECT projection
    (distance_km) and WHERE exact circle refinement.
    """
    centre_lat = func.radians(sa.literal(geo.lat))
    row_lat = func.radians(Listing.latitude)
    half_dlat = func.radians(Listing.latitude - sa.literal(geo.lat)) / 2
    half_dlng = func.radians(Listing.longitude - sa.literal(geo.lng)) / 2
    hav = func.sin(half_dlat) * func.sin(half_dlat) + func.cos(centre_lat) * func.cos(
        row_lat
    ) * func.sin(half_dlng) * func.sin(half_dlng)
    return _EARTH_RADIUS_KM * 2 * func.asin(func.sqrt(hav))


def _tsquery(q: str):
    """Plain tsquery with explicit regconfig cast to avoid asyncpg VARCHAR mismatch."""
    return func.plainto_tsquery(sa.text(f"'{FTS_CONFIG}'::regconfig"), q)


def _relevance_expr(q: str, tsq: ColumnElement[Any] | None = None):
    ts = tsq if tsq is not None else _tsquery(q)
    return func.ts_rank(Listing.search_vector, ts)


def _geo_where_clauses(geo: GeoFilter, dist_expr: ColumnElement[float] | None = None):
    """Bounding box (btree-friendly) + exact haversine <= radius."""
    box = bounding_box(geo.lat, geo.lng, geo.radius_km)
    d = dist_expr if dist_expr is not None else _distance_expr(geo)
    return [
        Listing.latitude.between(box.south, box.north),
        Listing.longitude.between(box.west, box.east),
        d <= geo.radius_km,
    ]


def _browse_where_clauses(
    f: ListingFilters,
    dist_expr: ColumnElement[float] | None = None,
    tsq: ColumnElement[Any] | None = None,
):
    """All WHERE predicates — shared by page query and count query to keep has_more truthful."""
    clauses: list[ColumnElement[bool]] = [
        Listing.app_id == f.app_id,
        Listing.status == (f.status or DEFAULT_STATUS),
    ]
    if f.q:
        t = tsq if tsq is not None else _tsquery(f.q)
        clauses.append(Listing.search_vector.op("@@")(t))
    if f.category is not None:
        clauses.append(Listing.category == f.category)
    if f.condition is not None:
        clauses.append(Listing.condition == f.condition)
    if f.price_min_cents is not None:
        clauses.append(Listing.price_cents >= f.price_min_cents)
    if f.price_max_cents is not None:
        clauses.append(Listing.price_cents <= f.price_max_cents)
    if f.seller_user_id is not None:
        clauses.append(Listing.seller_id == f.seller_user_id)
    if f.geo is not None:
        clauses.extend(_geo_where_clauses(f.geo, dist_expr=dist_expr))
    return clauses


def _browse_order_by(
    sort: str | None, q: str | None, tsq: ColumnElement[Any] | None = None
):
    """Sort keys always ending in total order (created_at DESC, id DESC) to make offset pagination stable."""
    ordering: list[ColumnElement[Any]] = []
    if sort == SORT_PRICE_ASC:
        ordering.append(Listing.price_cents.asc())
    elif sort == SORT_PRICE_DESC:
        ordering.append(Listing.price_cents.desc())
    elif sort == SORT_RELEVANCE or (sort is None and q is not None):
        # relevance default when q present; explicit relevance allowed
        if q is not None:
            ordering.append(desc(_relevance_expr(q, tsq=tsq)))
    # newest default when q absent is created_at DESC — which we always append below anyway
    ordering.append(Listing.created_at.desc())
    ordering.append(Listing.id.desc())
    return ordering


def build_browse_query(f: ListingFilters) -> Select[tuple[Listing, float | None]]:
    """Page query returning (Listing, distance_km). distance_km NULL when no geo."""
    dist_expr = _distance_expr(f.geo) if f.geo is not None else None
    tsq = _tsquery(f.q) if f.q else None

    distance_label = (
        dist_expr.label("distance_km")
        if dist_expr is not None
        else sa.cast(sa.null(), sa.Float).label("distance_km")
    )

    stmt = select(Listing, distance_label).where(
        *_browse_where_clauses(f, dist_expr=dist_expr, tsq=tsq)
    )
    stmt = stmt.order_by(*_browse_order_by(f.sort, f.q, tsq=tsq))
    stmt = stmt.limit(f.limit).offset(f.offset)
    return stmt


def build_count_query(f: ListingFilters) -> Select[tuple[int]]:
    dist_expr = _distance_expr(f.geo) if f.geo is not None else None
    tsq = _tsquery(f.q) if f.q else None
    return (
        select(func.count())
        .select_from(Listing)
        .where(*_browse_where_clauses(f, dist_expr=dist_expr, tsq=tsq))
    )


# ---- Public helpers used by route layer + tests ----


def count_results(session: Session, f: ListingFilters) -> int:
    return session.execute(build_count_query(f)).scalar_one()


def run_query(
    session: Session, f: ListingFilters
) -> list[tuple[Listing, float | None]]:
    """Return page of (listing, distance_km) tuples."""
    return list(session.execute(build_browse_query(f)).all())


def run_query_legacy(session: Session, f: ListingFilters) -> list[Listing]:
    """Compat shim for old slice callers expecting List[Listing] only."""
    rows = run_query(session, f)
    return [r[0] for r in rows]


def python_distance_km(f: ListingFilters, listing: Listing) -> float | None:
    """Python-side distance for cases where row has lat/lng but SQL projection was NULL (or for tests)."""
    if f.geo is None or listing.latitude is None or listing.longitude is None:
        return None
    try:
        return haversine_km(f.geo.lat, f.geo.lng, listing.latitude, listing.longitude)
    except ValueError:
        return None


# ---- Unit-conversion helper exposed for route layer ----
def parse_geo(
    lat: float | None,
    lng: float | None,
    radius: float | None,
    unit: str | None,
) -> GeoFilter | None:
    """Parse lat/lng/radius/unit query params into GeoFilter or None.

    Raises ValueError with user-facing message on validation failure (mapped to 400 validation_failed).
    """
    if lat is None and lng is None and radius is None:
        return None
    # pairwise check handled in route but also here defensively
    if (lat is None) != (lng is None):
        raise ValueError("lat and lng are required together for geo filtering")
    if lat is None or lng is None:
        return None
    raw_radius = radius if radius is not None else 25.0
    raw_unit_str = unit if unit is not None else "km"
    try:
        radius_unit = RadiusUnit(raw_unit_str)
    except ValueError:
        raise ValueError(f"invalid unit. Valid values: {[u.value for u in RadiusUnit]}")
    km = to_km(raw_radius, radius_unit)
    if km > 100:
        raise ValueError(f"radius must be <= 100 km after conversion (got {km:.2f} km)")
    return GeoFilter(lat=lat, lng=lng, radius_km=km)
