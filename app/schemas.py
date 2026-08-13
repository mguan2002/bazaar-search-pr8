"""Pydantic response schemas (design doc §3.2, PR1 contract T282737844).

P2-owned Listing shape reproduced per openapi/listings.yaml:
 - seller_user_id replaces slice's seller_id
 - distance_km present when lat/lng supplied
 - actions[] NOT on list response (detail only)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import Listing


class ListingResponse(BaseModel):
    """Single listing in browse/search response. Matches openapi fragment § components/schemas/Listing."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    seller_user_id: str
    title: str
    description: str
    price_cents: int
    category: str
    condition: str
    latitude: float | None = None
    longitude: float | None = None
    image_url: str | None = None
    status: str
    created_at: datetime
    distance_km: float | None = None

    @classmethod
    def from_listing(
        cls, listing: Listing, distance_km: float | None = None
    ) -> "ListingResponse":
        # model seller_id -> API seller_user_id
        return cls(
            id=listing.id,
            seller_user_id=listing.seller_id,
            title=listing.title,
            description=listing.description,
            price_cents=listing.price_cents,
            category=listing.category,
            condition=listing.condition,
            latitude=listing.latitude,
            longitude=listing.longitude,
            image_url=listing.image_url,
            status=listing.status,
            created_at=listing.created_at,
            distance_km=round(distance_km, 3) if distance_km is not None else None,
        )


class Pagination(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool


class ListingsPage(BaseModel):
    data: list[ListingResponse]
    pagination: Pagination


# ---- Error envelope per S2 middleware T283279748 ----


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
