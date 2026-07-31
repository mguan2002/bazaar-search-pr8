"""Seed the demo marketplace with realistic listings (design doc §4.4).

  - 150 listings
  - category mix: furniture 30% / electronics 25% / apparel 20% / baby_kids 15% / other 10%
  - clustered around 3 neighborhoods in a single metro (San Francisco here)
  - realistic per-category price ranges ($20–$2000)
  - Picsum stock photo URLs (no upload dependency)
  - 20 unique sellers

Run:  uv run python seed.py [--app-id demo-app] [--reset]
Doubles as the integration-test fixture.
"""

from __future__ import annotations

import argparse
import random

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import CATEGORIES, Condition, Listing, ListingStatus

TOTAL = 150
CATEGORY_MIX = {
    "furniture": 0.30,
    "electronics": 0.25,
    "apparel": 0.20,
    "baby_kids": 0.15,
    "other": 0.10,
}

# 3 SF neighborhood cluster centers (lat, lng).
NEIGHBORHOODS = [
    ("Mission", 37.7599, -122.4148),
    ("Marina", 37.8037, -122.4368),
    ("Sunset", 37.7510, -122.4869),
]

PRICE_RANGES_CENTS = {  # realistic $20–$2000 per category
    "furniture": (5_000, 200_000),
    "electronics": (3_000, 180_000),
    "apparel": (2_000, 25_000),
    "baby_kids": (2_000, 40_000),
    "other": (2_000, 60_000),
}

NOUNS = {
    "furniture": ["Leather Couch", "Oak Dining Table", "Standing Desk", "Bookshelf",
                  "Armchair", "Bed Frame", "Coffee Table", "Wardrobe"],
    "electronics": ["iPhone 14", "MacBook Pro", "4K Monitor", "Bluetooth Speaker",
                    "Mechanical Keyboard", "Noise-Cancelling Headphones", "Game Console",
                    "Digital Camera"],
    "apparel": ["Leather Jacket", "Wool Coat", "Running Shoes", "Denim Jeans",
                "Silk Dress", "Cashmere Sweater", "Sneakers", "Rain Boots"],
    "baby_kids": ["Baby Stroller", "Crib", "High Chair", "Car Seat", "Play Mat",
                  "Kids Bicycle", "Toy Kitchen", "Diaper Bag"],
    "other": ["Mountain Bike", "Acoustic Guitar", "Camping Tent", "Kitchen Blender",
              "Yoga Mat", "Board Game Set", "Espresso Machine", "Tool Kit"],
}
ADJECTIVES = ["barely used", "excellent condition", "vintage", "modern", "compact",
              "premium", "like-new", "gently used", "classic", "sturdy"]


def _counts() -> dict[str, int]:
    counts = {c: round(TOTAL * pct) for c, pct in CATEGORY_MIX.items()}
    # fix rounding drift so the total is exactly TOTAL
    drift = TOTAL - sum(counts.values())
    counts["furniture"] += drift
    return counts


def build_listings(app_id: str, rng: random.Random) -> list[Listing]:
    sellers = [f"seller_{i:02d}" for i in range(20)]
    listings: list[Listing] = []
    for category, n in _counts().items():
        lo, hi = PRICE_RANGES_CENTS[category]
        for _ in range(n):
            noun = rng.choice(NOUNS[category])
            adj = rng.choice(ADJECTIVES)
            _, clat, clng = rng.choice(NEIGHBORHOODS)
            listings.append(
                Listing(
                    app_id=app_id,
                    seller_id=rng.choice(sellers),
                    title=f"{noun} ({adj})",
                    description=f"A {adj} {noun.lower()}. Pickup only. Serious buyers.",
                    price_cents=rng.randint(lo, hi),
                    category=category,
                    condition=rng.choice(list(Condition)).value,
                    latitude=round(clat + rng.uniform(-0.01, 0.01), 6),
                    longitude=round(clng + rng.uniform(-0.01, 0.01), 6),
                    image_url=f"https://picsum.photos/seed/{noun.replace(' ', '')}{rng.randint(1, 9999)}/400/300",
                    status=ListingStatus.active.value,
                )
            )
    rng.shuffle(listings)
    return listings


def seed(app_id: str = "demo-app", reset: bool = False, seed_value: int = 42) -> int:
    rng = random.Random(seed_value)
    session = SessionLocal()
    try:
        if reset:
            session.execute(delete(Listing).where(Listing.app_id == app_id))
        rows = build_listings(app_id, rng)
        session.add_all(rows)
        session.commit()
        return len(rows)
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", default="demo-app")
    parser.add_argument("--reset", action="store_true", help="delete this app's listings first")
    args = parser.parse_args()
    n = seed(app_id=args.app_id, reset=args.reset)
    print(f"Seeded {n} listings for app_id={args.app_id!r}")
    assert n == TOTAL, f"expected {TOTAL}, got {n}"
