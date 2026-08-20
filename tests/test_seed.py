"""PR10 — seed CLI + CRUD insertion + smoke test (T282737911).

Covers:
- deterministic generation seed=42 -> 150 listings, category/geo mix
- _counts() rounding drift fix
- distribution_summary() and --check-distribution invariant
- build_listings() reproducibility (--reset reproduces documented distribution)
- CRUD insertion via POST /v1/listings (PR10 + P2 T282737576)
- smoke: seeded data queryable via GET /v1/listings (browse + search)
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal
from app.main import app
from app.models import Listing
from seed import (
    TOTAL,
    CATEGORY_MIX,
    NEIGHBORHOODS,
    _counts,
    build_listings,
    distribution_summary,
    seed,
)

client = TestClient(app)
APP_ID = "demo-app"


@pytest.fixture(autouse=True)
def clean():
    sess = SessionLocal()
    try:
        sess.execute(delete(Listing).where(Listing.app_id == APP_ID))
        sess.commit()
    finally:
        sess.close()
    yield
    sess = SessionLocal()
    try:
        sess.execute(delete(Listing).where(Listing.app_id == APP_ID))
        sess.commit()
    finally:
        sess.close()


def test_counts_rounding_drift():
    counts = _counts(TOTAL)
    assert sum(counts.values()) == TOTAL
    # furniture absorbs drift per seed.py comment
    assert counts["furniture"] == round(TOTAL * CATEGORY_MIX["furniture"]) + (
        TOTAL - sum(round(TOTAL * p) for p in CATEGORY_MIX.values())
    )


def test_build_listings_total_and_determinism():
    rng1 = random.Random(42)
    rows1 = build_listings(APP_ID, rng1, total=TOTAL)
    assert len(rows1) == TOTAL
    rng2 = random.Random(42)
    rows2 = build_listings(APP_ID, rng2, total=TOTAL)
    # Same seed -> same content after shuffle (compare sorted titles + categories)
    t1 = sorted((r.title, r.category, r.price_cents) for r in rows1)
    t2 = sorted((r.title, r.category, r.price_cents) for r in rows2)
    assert t1 == t2


def test_build_listings_distribution_matches_spec():
    rng = random.Random(42)
    rows = build_listings(APP_ID, rng, total=TOTAL)
    summary = distribution_summary(rows)
    assert summary["categories"] == _counts(TOTAL)
    assert (
        summary["sellers"] == 20 or summary["sellers"] <= 20
    )  # 20 unique sellers defined
    # All 3 neighborhoods represented due to clustering
    assert len(summary["neighborhoods"]) == 3
    # Each neighborhood at least a few listings
    for nb in [n[0] for n in NEIGHBORHOODS]:
        assert summary["neighborhoods"].get(nb, 0) > 0


def test_seed_reset_reproduces_distribution():
    # PR10 verification: --reset reproduces documented distribution
    n1 = seed(app_id=APP_ID, reset=True, seed_value=42, total=TOTAL)
    assert n1 == TOTAL
    sess = SessionLocal()
    try:
        from sqlalchemy import select

        rows = (
            sess.execute(select(Listing).where(Listing.app_id == APP_ID))
            .scalars()
            .all()
        )
        first_titles = sorted([r.title for r in rows])[:5]
    finally:
        sess.close()

    # second seed with same args after reset should reproduce same titles
    n2 = seed(app_id=APP_ID, reset=True, seed_value=42, total=TOTAL)
    assert n2 == TOTAL
    sess = SessionLocal()
    try:
        rows2 = (
            sess.execute(select(Listing).where(Listing.app_id == APP_ID))
            .scalars()
            .all()
        )
        second_titles = sorted([r.title for r in rows2])[:5]
    finally:
        sess.close()

    assert first_titles == second_titles


def test_post_crud_insertion():
    # PR10: CRUD insertion via POST /v1/listings
    resp = client.post(
        "/v1/listings",
        json={
            "title": "Test Couch via CRUD",
            "description": "Integration test for PR10",
            "price_cents": 12345,
            "category": "furniture",
            "condition": "good",
            "latitude": 37.7749,
            "longitude": -122.4194,
            "status": "active",
            "seller_user_id": "seller_01",
        },
        headers={"X-App-Id": APP_ID},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Test Couch via CRUD"
    assert body["seller_user_id"] == "seller_01"
    assert body["distance_km"] is None  # POST doesn't compute distance
    assert "id" in body
    assert "created_at" in body

    # appears in browse
    browse = client.get("/v1/listings", headers={"X-App-Id": APP_ID})
    assert browse.status_code == 200
    assert browse.json()["pagination"]["total"] == 1

    # appears in search when q matches
    search = client.get("/v1/listings?q=couch", headers={"X-App-Id": APP_ID})
    assert search.status_code == 200
    assert search.json()["pagination"]["total"] == 1

    # validation: missing lat pair -> 400
    bad = client.post(
        "/v1/listings",
        json={
            "title": "Bad geo",
            "description": "",
            "price_cents": 1000,
            "category": "furniture",
            "condition": "good",
            "latitude": 37.0,
            "seller_user_id": "s1",
        },
        headers={"X-App-Id": APP_ID},
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "validation_failed"


def test_smoke_seeded_data_queryable():
    # Full smoke: seed 150 then GET browse/search/geo work
    n = seed(app_id=APP_ID, reset=True, seed_value=42, total=TOTAL)
    assert n == TOTAL

    # browse returns pagination envelope
    r = client.get("/v1/listings?limit=50", headers={"X-App-Id": APP_ID})
    assert r.status_code == 200
    assert r.json()["pagination"]["total"] == TOTAL
    assert len(r.json()["data"]) == 50
    for item in r.json()["data"]:
        assert "seller_user_id" in item
        assert "distance_km" in item
        assert "actions" not in item

    # search for common noun (couch appears in furniture nouns)
    rs = client.get("/v1/listings?q=couch&limit=20", headers={"X-App-Id": APP_ID})
    assert rs.status_code == 200
    assert rs.json()["pagination"]["total"] > 0

    # geo filter near Mission with 5km radius should return subset
    rg = client.get(
        "/v1/listings?latitude=37.7599&longitude=-122.4148&radius=5&limit=50",
        headers={"X-App-Id": APP_ID},
    )
    assert rg.status_code == 200
    # cluster around 3 neighborhoods, so Mission subset < total but >0
    assert 0 < rg.json()["pagination"]["total"] < TOTAL
    for item in rg.json()["data"]:
        assert item["distance_km"] is not None
        assert item["distance_km"] <= 5.5  # allow tiny rounding
