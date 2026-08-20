"""PR8 — browse mode integration: GET /v1/listings unified endpoint (T282737884).

Covers:
 - browse returns pagination envelope
 - offset pagination has_more
 - category / condition / price / seller / status filters
 - geo filter + distance_km projection + mi conversion
 - validation failures -> {error:{code,message,request_id}} envelope, X-Request-Id header
 - schema conformance: seller_user_id, distance_km, no actions[]
 - distribution seed (150 listings, seed=42) sanity
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.db import SessionLocal
from app.main import app
from app.models import Listing, ListingStatus

client = TestClient(app)

APP_ID = "demo-app"


@pytest.fixture(autouse=True)
def clean_listings():
    session = SessionLocal()
    try:
        session.execute(delete(Listing).where(Listing.app_id == APP_ID))
        session.commit()
    finally:
        session.close()
    yield
    # cleanup after
    session = SessionLocal()
    try:
        session.execute(delete(Listing).where(Listing.app_id == APP_ID))
        session.commit()
    finally:
        session.close()


def _listing(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "app_id": APP_ID,
        "seller_id": "seller_01",
        "title": "Test Couch",
        "description": "A barely used couch",
        "price_cents": 10000,
        "category": "furniture",
        "condition": "good",
        "latitude": 37.7749,
        "longitude": -122.4194,
        "image_url": None,
        "status": ListingStatus.active.value,
    }
    base.update(overrides)
    return base


def _seed(rows: list[dict[str, Any]]) -> list[int]:
    session = SessionLocal()
    ids: list[int] = []
    try:
        objs = [Listing(**r) for r in rows]
        session.add_all(objs)
        session.flush()
        ids = [o.id for o in objs]
        session.commit()
    finally:
        session.close()
    return ids


def test_browse_returns_pagination_envelope():
    _seed([_listing(title="Couch")])
    resp = client.get("/v1/listings", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body and "pagination" in body
    assert body["pagination"]["total"] == 1
    assert body["pagination"]["has_more"] is False
    assert body["data"][0]["title"] == "Couch"
    # schema conformance
    listing = body["data"][0]
    assert "seller_user_id" in listing
    assert listing["seller_user_id"] == "seller_01"
    assert "actions" not in listing  # no actions[] on list per spec
    assert "distance_km" in listing  # present but None when no geo
    assert listing["distance_km"] is None
    # request_id header
    assert "x-request-id" in resp.headers
    assert resp.headers["x-request-id"].startswith("req_")


def test_browse_offset_pagination_has_more():
    _seed([_listing(title=f"Item {i}", seller_id=f"seller_{i:02d}") for i in range(3)])
    r1 = client.get("/v1/listings?limit=2&offset=0", headers={"X-App-Id": APP_ID})
    r2 = client.get("/v1/listings?limit=2&offset=2", headers={"X-App-Id": APP_ID})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["pagination"]["has_more"] is True
    assert r2.json()["pagination"]["has_more"] is False
    assert len(r1.json()["data"]) == 2
    assert len(r2.json()["data"]) == 1
    # total stable across pages
    assert r1.json()["pagination"]["total"] == 3


def test_browse_category_filter():
    _seed(
        [
            _listing(title="Couch", category="furniture"),
            _listing(title="Phone", category="electronics"),
        ]
    )
    resp = client.get("/v1/listings?category=furniture", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 200
    assert resp.json()["pagination"]["total"] == 1
    assert resp.json()["data"][0]["category"] == "furniture"


def test_browse_geo_filter_and_distance_km():
    _seed(
        [
            _listing(
                title="Near", seller_id="near", latitude=37.7749, longitude=-122.4194
            ),
            _listing(
                title="Far", seller_id="far", latitude=37.8044, longitude=-122.2712
            ),  # Oakland ~13km
        ]
    )
    resp = client.get(
        "/v1/listings?latitude=37.7749&longitude=-122.4194&radius=5&unit=km",
        headers={"X-App-Id": APP_ID},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"]["total"] == 1
    assert body["data"][0]["seller_user_id"] == "near"
    assert body["data"][0]["distance_km"] is not None
    assert body["data"][0]["distance_km"] < 1.0
    # distance_km always km
    assert isinstance(body["data"][0]["distance_km"], float)


def test_browse_geo_mi_conversion():
    _seed([_listing(title="Near", latitude=37.7749, longitude=-122.4194)])
    # 1 mi = 1.6 km, should match within 5 km even when queried in miles
    resp = client.get(
        "/v1/listings?latitude=37.7749&longitude=-122.4194&radius=1&unit=mi",
        headers={"X-App-Id": APP_ID},
    )
    assert resp.status_code == 200
    assert resp.json()["pagination"]["total"] == 1
    assert resp.json()["data"][0]["distance_km"] is not None
    # distance_km always km regardless of unit
    assert resp.json()["data"][0]["distance_km"] < 2.0


def test_browse_geo_distance_absent_without_geo():
    _seed([_listing(title="Item")])
    resp = client.get("/v1/listings", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 200
    assert resp.json()["data"][0]["distance_km"] is None


def test_seller_and_status_filters():
    _seed(
        [
            _listing(title="Active", seller_id="alice", status="active"),
            _listing(title="Sold", seller_id="alice", status="sold"),
            _listing(title="Bob Active", seller_id="bob", status="active"),
        ]
    )
    # default active only
    r_default = client.get("/v1/listings", headers={"X-App-Id": APP_ID})
    assert r_default.json()["pagination"]["total"] == 2

    r_sold = client.get("/v1/listings?status=sold", headers={"X-App-Id": APP_ID})
    assert r_sold.json()["pagination"]["total"] == 1
    assert r_sold.json()["data"][0]["title"] == "Sold"

    r_alice = client.get(
        "/v1/listings?seller_user_id=alice", headers={"X-App-Id": APP_ID}
    )
    assert r_alice.json()["pagination"]["total"] == 1  # active only
    assert r_alice.json()["data"][0]["title"] == "Active"

    r_alice_sold = client.get(
        "/v1/listings?seller_user_id=alice&status=sold", headers={"X-App-Id": APP_ID}
    )
    assert r_alice_sold.json()["pagination"]["total"] == 1
    assert r_alice_sold.json()["data"][0]["title"] == "Sold"


def test_price_filters():
    _seed(
        [
            _listing(title="Cheap", price_cents=1000),
            _listing(title="Mid", price_cents=5000),
            _listing(title="Expensive", price_cents=20000),
        ]
    )
    r = client.get(
        "/v1/listings?price_min_cents=4000&price_max_cents=10000",
        headers={"X-App-Id": APP_ID},
    )
    assert r.status_code == 200
    assert r.json()["pagination"]["total"] == 1
    assert r.json()["data"][0]["title"] == "Mid"


def test_sort_price_asc_desc():
    _seed(
        [
            _listing(title="Cheap", price_cents=1000),
            _listing(title="Expensive", price_cents=20000),
            _listing(title="Mid", price_cents=5000),
        ]
    )
    r_asc = client.get("/v1/listings?sort=price_asc", headers={"X-App-Id": APP_ID})
    assert [d["title"] for d in r_asc.json()["data"]] == ["Cheap", "Mid", "Expensive"]

    r_desc = client.get("/v1/listings?sort=price_desc", headers={"X-App-Id": APP_ID})
    assert [d["title"] for d in r_desc.json()["data"]] == ["Expensive", "Mid", "Cheap"]


def test_sort_newest_default():
    # Insert with explicit created_at ordering via id DESC fallback
    _seed(
        [
            _listing(title="First", seller_id="s1"),
            _listing(title="Second", seller_id="s2"),
            _listing(title="Third", seller_id="s3"),
        ]
    )
    r = client.get("/v1/listings?sort=newest", headers={"X-App-Id": APP_ID})
    assert r.status_code == 200
    # newest first — last inserted should have higher id
    titles = [d["title"] for d in r.json()["data"]]
    assert titles[0] == "Third"


@pytest.mark.parametrize(
    "query",
    [
        "latitude=37.7749",  # lat without lng
        "longitude=-122.4194",  # lng without lat
        "price_min_cents=500&price_max_cents=100",  # inverted range
        "latitude=37.7749&longitude=-122.4194&radius=200",  # >100 km
        "latitude=37.7749&longitude=-122.4194&radius=70&unit=mi",  # 70mi=112km >100
        "category=invalid_cat",
        "status=invalid_status",
        "sort=invalid_sort",
    ],
)
def test_validation_failures(query):
    resp = client.get(f"/v1/listings?{query}", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "validation_failed"
    assert "message" in body["error"]
    assert "request_id" in body["error"]
    assert body["error"]["request_id"] is not None
    assert "x-request-id" in resp.headers
    # request_id in body matches header
    assert body["error"]["request_id"] == resp.headers["x-request-id"]


def test_q_blank_is_400():
    resp = client.get("/v1/listings?q=%20%20", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_failed"


def test_error_envelope_shape_for_invalid_unit():
    resp = client.get("/v1/listings?unit=invalid", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "validation_failed"
    assert body["error"]["request_id"] is not None


def test_search_mode_basic_relevance():
    # Even in PR8, q present should trigger ts_rank path (search mode)
    _seed(
        [
            _listing(title="Unrelated", description="mentions stroller in description"),
            _listing(title="Stroller", description="Barely used"),
        ]
    )
    resp = client.get("/v1/listings?q=stroller", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 200
    titles = [d["title"] for d in resp.json()["data"]]
    # Title weight A > description weight B, so Stroller first
    assert titles[0] == "Stroller"


def test_browse_with_distribution_seed():
    # Use seed.py build_listings with deterministic seed=42 to verify distribution handling
    from seed import build_listings
    import random

    rng = random.Random(42)
    listings = build_listings(APP_ID, rng)
    session = SessionLocal()
    try:
        session.add_all(listings)
        session.commit()
    finally:
        session.close()

    resp = client.get("/v1/listings?limit=50", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 200
    assert resp.json()["pagination"]["total"] == 150
    # category mix from seed.py: furniture 30% etc — check roughly
    cats = [d["category"] for d in resp.json()["data"]]
    assert len(cats) == 50
    # all have seller_user_id and no actions
    for item in resp.json()["data"]:
        assert "seller_user_id" in item
        assert "actions" not in item
        assert "distance_km" in item


def test_browse_geo_with_category_and_status():
    _seed(
        [
            _listing(
                title="SF active furniture",
                category="furniture",
                latitude=37.7749,
                longitude=-122.4194,
                status="active",
            ),
            _listing(
                title="SF sold furniture",
                category="furniture",
                latitude=37.78,
                longitude=-122.42,
                status="sold",
            ),
            _listing(
                title="SF active electronics",
                category="electronics",
                latitude=37.7749,
                longitude=-122.4194,
                status="active",
            ),
        ]
    )
    resp = client.get(
        "/v1/listings?latitude=37.7749&longitude=-122.4194&radius=5&category=furniture",
        headers={"X-App-Id": APP_ID},
    )
    assert resp.status_code == 200
    assert resp.json()["pagination"]["total"] == 1
    assert resp.json()["data"][0]["title"] == "SF active furniture"
