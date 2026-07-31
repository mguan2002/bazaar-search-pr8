"""SQLAlchemy models.

PROVISIONAL CONTRACT — reconcile with S2 (T282737576). The listings table is owned by
S2; this mirrors the field list agreed in the design doc §2.1 so P3 can build search
ahead of S2. `search_vector` + its indexes (§3.1) are P3's contribution to that table.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Float,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Condition(str, enum.Enum):
    new = "new"
    like_new = "like_new"
    good = "good"
    fair = "fair"


class ListingStatus(str, enum.Enum):
    active = "active"
    sold = "sold"
    removed = "removed"


# Category is a plain string here; exact enum values are P2-owned (design doc §9 Q2).
CATEGORIES = ["furniture", "electronics", "apparel", "baby_kids", "other"]


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seller_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # condition/status are stored as VARCHAR (enum *values*), not native PG enums, to
    # match S2's provisional table and stay portable. The Condition/ListingStatus classes
    # remain the source of valid values for validation and seeding.
    condition: Mapped[str] = mapped_column(String(16), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ListingStatus.active.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # §3.1 — weighted full-text vector, maintained by Postgres (GENERATED ... STORED),
    # so a listing is searchable the instant it is written (no trigger, no app logic).
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'B')",
            persisted=True,
        ),
        nullable=False,
    )

    # Indexes (§3.1) — GIN on search_vector, composite browse index (created_at DESC),
    # and geo b-tree indexes — are created by the Alembic migration, which is the DDL
    # artifact P3 hands to S2. Keeping them out of the model avoids duplicate/conflicting
    # definitions since the schema is applied via `alembic upgrade`, not create_all.
