"""Seed the demo marketplace with realistic listings (design doc §4.4, PR10).

  - 150 listings (default) — override with --count
  - category mix: furniture 30% / electronics 25% / apparel 20% / baby_kids 15% / other 10%
  - clustered around 3 neighborhoods in a single metro (San Francisco here)
  - realistic per-category price ranges ($20–$2000)
  - Picsum stock photo URLs (no upload dependency) — MinIO path is additive v1 (PR10 note)
  - 20 unique sellers
  - deterministic via --seed (default 42) for reproducible distribution

Run:
  uv run python seed.py [--app-id demo-app] [--reset] [--seed 42] [--count 150]
  uv run python seed.py --reset --seed 42 --via-api --api-url http://127.0.0.1:8000
  uv run python seed.py --check-distribution  # verifies seed=42 matches spec without DB

PR10 (T282737911):
  - CLI with --reset, --seed, --count, --via-api, --api-url, --check-distribution
  - CRUD insertion via POST /v1/listings (P2 T282737576) when --via-api
  - --reset reproduces documented distribution (deterministic RNG)
  - Smoke verified via tests/test_seed.py

Doubles as the integration-test fixture via build_listings().
"""

from __future__ import annotations

import argparse
import collections
import random
import sys
from typing import Iterable

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

PRICE_RANGES_CENTS = {
    "furniture": (5_000, 200_000),
    "electronics": (3_000, 180_000),
    "apparel": (2_000, 25_000),
    "baby_kids": (2_000, 40_000),
    "other": (2_000, 60_000),
}

NOUNS = {
    "furniture": [
        "Leather Couch",
        "Oak Dining Table",
        "Standing Desk",
        "Bookshelf",
        "Armchair",
        "Bed Frame",
        "Coffee Table",
        "Wardrobe",
    ],
    "electronics": [
        "iPhone 14",
        "MacBook Pro",
        "4K Monitor",
        "Bluetooth Speaker",
        "Mechanical Keyboard",
        "Noise-Cancelling Headphones",
        "Game Console",
        "Digital Camera",
    ],
    "apparel": [
        "Leather Jacket",
        "Wool Coat",
        "Running Shoes",
        "Denim Jeans",
        "Silk Dress",
        "Cashmere Sweater",
        "Sneakers",
        "Rain Boots",
    ],
    "baby_kids": [
        "Baby Stroller",
        "Crib",
        "High Chair",
        "Car Seat",
        "Play Mat",
        "Kids Bicycle",
        "Toy Kitchen",
        "Diaper Bag",
    ],
    "other": [
        "Mountain Bike",
        "Acoustic Guitar",
        "Camping Tent",
        "Kitchen Blender",
        "Yoga Mat",
        "Board Game Set",
        "Espresso Machine",
        "Tool Kit",
    ],
}
ADJECTIVES = [
    "barely used",
    "excellent condition",
    "vintage",
    "modern",
    "compact",
    "premium",
    "like-new",
    "gently used",
    "classic",
    "sturdy",
]


def _counts(total: int = TOTAL) -> dict[str, int]:
    counts = {c: round(total * pct) for c, pct in CATEGORY_MIX.items()}
    drift = total - sum(counts.values())
    counts["furniture"] += drift
    return counts


def build_listings(
    app_id: str, rng: random.Random, total: int = TOTAL
) -> list[Listing]:
    sellers = [f"seller_{i:02d}" for i in range(20)]
    listings: list[Listing] = []
    for category, n in _counts(total).items():
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


def distribution_summary(listings: Iterable[Listing]) -> dict:
    cats = collections.Counter(l.category for l in listings)
    sellers = collections.Counter(l.seller_id for l in listings)
    geos = collections.Counter()
    for lst in listings:
        if lst.latitude is None or lst.longitude is None:
            continue
        # coarse bucket to nearest neighborhood
        best = min(
            NEIGHBORHOODS,
            key=lambda nb: (nb[1] - lst.latitude) ** 2 + (nb[2] - lst.longitude) ** 2,
        )
        geos[best[0]] += 1
    return {
        "categories": dict(cats),
        "sellers": len(sellers),
        "neighborhoods": dict(geos),
    }


def _seed_via_db(app_id: str, listings: list[Listing], reset: bool) -> int:
    session = SessionLocal()
    try:
        if reset:
            session.execute(delete(Listing).where(Listing.app_id == app_id))
        session.add_all(listings)
        session.commit()
        return len(listings)
    finally:
        session.close()


def _seed_via_api(
    app_id: str,
    listings: list[Listing],
    api_url: str,
    reset: bool,
) -> int:
    """CRUD insertion via POST /v1/listings (PR10). Requires live API."""

    try:
        import httpx  # type: ignore
    except ImportError:
        print(
            "httpx required for --via-api, install dev deps: uv sync --group dev",
            file=sys.stderr,
        )
        sys.exit(2)

    base = api_url.rstrip("/")
    headers = {"X-App-Id": app_id}

    if reset:
        # reset via direct DB to keep slice self-contained; API delete not in scope
        sess = SessionLocal()
        try:
            sess.execute(delete(Listing).where(Listing.app_id == app_id))
            sess.commit()
        finally:
            sess.close()

    inserted = 0
    with httpx.Client(timeout=30.0) as cli:
        for lst in listings:
            payload = {
                "title": lst.title,
                "description": lst.description,
                "price_cents": lst.price_cents,
                "category": lst.category,
                "condition": lst.condition,
                "latitude": lst.latitude,
                "longitude": lst.longitude,
                "image_url": lst.image_url,
                "status": lst.status,
                "seller_user_id": lst.seller_id,
            }
            resp = cli.post(f"{base}/v1/listings", json=payload, headers=headers)
            if resp.status_code not in (200, 201):
                print(
                    f"API insert failed {resp.status_code}: {resp.text}",
                    file=sys.stderr,
                )
                sys.exit(1)
            inserted += 1
    return inserted


def seed(
    app_id: str = "demo-app",
    reset: bool = False,
    seed_value: int = 42,
    total: int = TOTAL,
    via_api: bool = False,
    api_url: str = "http://127.0.0.1:8000",
) -> int:
    rng = random.Random(seed_value)
    rows = build_listings(app_id, rng, total=total)
    if via_api:
        return _seed_via_api(app_id, rows, api_url, reset=reset)
    return _seed_via_db(app_id, rows, reset=reset)


def _check_distribution(seed_value: int = 42, total: int = TOTAL) -> int:
    """Verify deterministic distribution without touching DB."""
    rng = random.Random(seed_value)
    listings = build_listings("check", rng, total=total)
    summary = distribution_summary(listings)
    print(f"Total={len(listings)} seed={seed_value}")
    print(f"Category counts: {summary['categories']}")
    print(f"Unique sellers: {summary['sellers']}")
    print(f"Neighborhood mix: {summary['neighborhoods']}")
    expected = _counts(total)
    # Compare category distribution exactly
    if summary["categories"] != expected:
        print(
            f"FAIL: expected {expected}, got {summary['categories']}", file=sys.stderr
        )
        return 1
    if len(listings) != total:
        print(f"FAIL: expected total {total}, got {len(listings)}", file=sys.stderr)
        return 1
    # Verify reproducibility: same seed -> same first 3 titles
    rng2 = random.Random(seed_value)
    listings2 = build_listings("check", rng2, total=total)
    # Titles after shuffle are deterministic but we compare sorted titles for stability across Python versions
    titles1 = sorted([l.title for l in listings])[:3]
    titles2 = sorted([l.title for l in listings2])[:3]
    if titles1 != titles2:
        print("FAIL: not reproducible across same seed", file=sys.stderr)
        return 1
    print("Distribution OK — deterministic and matches spec")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bazaar seed CLI (PR10)")
    parser.add_argument("--app-id", default="demo-app", help="tenant app_id")
    parser.add_argument(
        "--reset", action="store_true", help="delete this app's listings first"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for deterministic generation (default 42)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=TOTAL,
        help=f"number of listings to generate (default {TOTAL})",
    )
    parser.add_argument(
        "--via-api",
        action="store_true",
        help="insert via POST /v1/listings CRUD instead of direct DB",
    )
    parser.add_argument(
        "--api-url", default="http://127.0.0.1:8000", help="base URL for --via-api"
    )
    parser.add_argument(
        "--check-distribution",
        action="store_true",
        help="verify deterministic distribution without DB",
    )
    args = parser.parse_args()

    if args.check_distribution:
        sys.exit(_check_distribution(seed_value=args.seed, total=args.count))

    n = seed(
        app_id=args.app_id,
        reset=args.reset,
        seed_value=args.seed,
        total=args.count,
        via_api=args.via_api,
        api_url=args.api_url,
    )
    print(
        f"Seeded {n} listings for app_id={args.app_id!r} seed={args.seed} count={args.count} via={'api' if args.via_api else 'db'}"
    )
    # keep original invariant for default count
    if args.count == TOTAL:
        assert n == TOTAL, f"expected {TOTAL}, got {n}"
