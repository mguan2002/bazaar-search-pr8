"""create listings table with full-text search vector and indexes (design doc §3.1)

Revision ID: 0001_listings_search
Revises:

NOTE ON OWNERSHIP (for the eventual merge into S2):
  - The base `listings` table (columns below) is S2-owned (T282737576). It is created
    here only so P3's search slice can run standalone. At merge time, drop this half if
    S2's table already matches.
  - P3's actual contribution to S2's table is the `search_vector` GENERATED column and
    the four indexes. That block is what you hand to S2 as a migration.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001_listings_search"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- S2-owned base table (provisional; reconcile with T282737576) ----------------
    op.execute(
        """
        CREATE TABLE listings (
            id           BIGSERIAL PRIMARY KEY,
            app_id       VARCHAR(64)  NOT NULL,
            seller_id    VARCHAR(64)  NOT NULL,
            title        VARCHAR(200) NOT NULL,
            description  TEXT         NOT NULL DEFAULT '',
            price_cents  BIGINT       NOT NULL,
            category     VARCHAR(32)  NOT NULL,
            condition    VARCHAR(16)  NOT NULL,
            latitude     DOUBLE PRECISION,
            longitude    DOUBLE PRECISION,
            image_url    VARCHAR(500),
            status       VARCHAR(16)  NOT NULL DEFAULT 'active',
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        """
    )

    # ---- P3's contribution: weighted full-text vector + search/browse indexes (§3.1) --
    op.execute(
        """
        ALTER TABLE listings ADD COLUMN search_vector tsvector
            GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(description, '')), 'B')
            ) STORED;
        """
    )
    op.execute(
        "CREATE INDEX idx_listings_search_vector ON listings USING GIN (search_vector);"
    )
    op.execute(
        "CREATE INDEX idx_listings_browse "
        "ON listings (app_id, status, category, created_at DESC);"
    )
    op.execute("CREATE INDEX idx_listings_lat ON listings (app_id, latitude);")
    op.execute("CREATE INDEX idx_listings_lng ON listings (app_id, longitude);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS listings;")
