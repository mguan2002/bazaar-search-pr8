"""Pydantic response schemas (design doc §3.2, PR1 contract T282737844).

P2-owned Listing shape reproduced per openapi/listings.yaml:
 - seller_user_id replaces slice's seller_id
 - distance_km present when lat/lng supplied
 - actions[] NOT on list response (detail only)

PR10 adds ListingCreate for POST /v1/listings CRUD insertion (T282737576).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import CATEGORIES, Condition, Listing, ListingStatus


class ListingCreate(BaseModel):
    """Create payload for POST /v1/listings (P2 owns shape, P3 provisional for PR10)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    price_cents: int = Field(..., ge=0)
    category: str
    condition: str
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    image_url: str | None = Field(default=None, max_length=500)
    status: str = Field(default=ListingStatus.active.value)
    seller_user_id: str = Field(default="seller_01", max_length=128)

    @field_validator("title")
    def _title_not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned

    @field_validator("category")
    def _valid_category(cls, v: str) -> str:
        if v not in set(CATEGORIES):
            raise ValueError(f"invalid category. Valid values: {CATEGORIES}")
        return v

    @field_validator("condition")
    def _valid_condition(cls, v: str) -> str:
        allowed = {c.value for c in Condition}
        if v not in allowed:
            raise ValueError(f"invalid condition. Valid values: {sorted(allowed)}")
        return v

    @field_validator("status")
    def _valid_status(cls, v: str) -> str:
        allowed = {s.value for s in ListingStatus}
        if v not in allowed:
            raise ValueError(f"invalid status. Valid values: {sorted(allowed)}")
        return v


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
