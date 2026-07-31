"""Pydantic response schemas (design doc §3.2).

`ListingResponse` is a PROVISIONAL mirror of P2's shared schema (§9 Q2/Q3) — reconcile
the exact field set (esp. image handling) with P2 at merge time.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import Listing


class ListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seller_id: str
    title: str
    description: str
    price_cents: int
    category: str
    condition: str
    latitude: float | None
    longitude: float | None
    image_url: str | None
    status: str
    created_at: datetime

    @classmethod
    def from_listing(cls, listing: Listing) -> "ListingResponse":
        return cls.model_validate(listing)


class Pagination(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool


class ListingsPage(BaseModel):
    data: list[ListingResponse]
    pagination: Pagination
