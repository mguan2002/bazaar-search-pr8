"""PR9 — search mode + §3.6 validation + top-5 relevance (T282737884).

Covers:
 - search mode with q: relevance default, title A > description B, price sort with q
 - geo + q combined, category + q, seller/status + q
 - offset pagination in search mode
 - top-5 relevance criterion (TDD §1.3): title hits outrank description-only, top 5 contain q
 - zero spec drift check: generated OpenAPI fragment has unified /v1/listings with required params
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal
from app.main import app
from app.models import Listing, ListingStatus

client = TestClient(app)
APP_ID = "demo-app"


@pytest.fixture(autouse=True)
def clean():
    session = SessionLocal()
    try:
        session.execute(delete(Listing).where(Listing.app_id == APP_ID))
        session.commit()
    finally:
        session.close()
    yield
    session = SessionLocal()
    try:
        session.execute(delete(Listing).where(Listing.app_id == APP_ID))
        session.commit()
    finally:
        session.close()


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "app_id": APP_ID,
        "seller_id": "seller_01",
        "title": "Item",
        "description": "",
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


def _seed(rows: list[dict[str, Any]]) -> None:
    session = SessionLocal()
    try:
        session.add_all([Listing(**r) for r in rows])
        session.commit()
    finally:
        session.close()


def test_search_default_sort_is_relevance_when_q_present():
    # When q present and sort omitted, effective sort is relevance (not newest)
    _seed(
        [
            _row(title="Unrelated", description="mentions stroller", seller_id="s1"),
            _row(title="Stroller", description="Barely used", seller_id="s2"),
        ]
    )
    resp = client.get("/v1/listings?q=stroller", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 200
    titles = [d["title"] for d in resp.json()["data"]]
    # Title weight A > B, so Stroller first
    assert titles[0] == "Stroller"
    # pagination still works
    assert resp.json()["pagination"]["total"] == 2


def test_search_relevance_title_outranks_description():
    _seed(
        [
            _row(
                title="Wooden table",
                description="Pairs with leather couch",
                seller_id="s1",
            ),
            _row(title="Leather couch", description="Well loved", seller_id="s2"),
            _row(title="Floor lamp", description="Brass", seller_id="s3"),
        ]
    )
    resp = client.get("/v1/listings?q=leather", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 200
    titles = [d["title"] for d in resp.json()["data"]]
    # Both Leather couch (title) and Wooden table (description) match, but title first
    assert titles[0] == "Leather couch"
    assert "Wooden table" in titles


def test_search_price_sort_with_q_is_allowed():
    # sort=price_asc with q is legitimate "cheapest matching stroller"
    _seed(
        [
            _row(title="Stroller cheap", price_cents=1000, seller_id="s1"),
            _row(title="Stroller expensive", price_cents=20000, seller_id="s2"),
        ]
    )
    resp = client.get(
        "/v1/listings?q=stroller&sort=price_asc", headers={"X-App-Id": APP_ID}
    )
    assert resp.status_code == 200
    assert [d["price_cents"] for d in resp.json()["data"]] == [1000, 20000]

    resp2 = client.get(
        "/v1/listings?q=stroller&sort=price_desc", headers={"X-App-Id": APP_ID}
    )
    assert [d["price_cents"] for d in resp2.json()["data"]] == [20000, 1000]


def test_search_geo_and_category_filters_combined():
    _seed(
        [
            _row(
                title="SF couch",
                category="furniture",
                latitude=37.7749,
                longitude=-122.4194,
                seller_id="near",
            ),
            _row(
                title="Oakland couch",
                category="furniture",
                latitude=37.8044,
                longitude=-122.2712,
                seller_id="far",
            ),
            _row(
                title="SF phone",
                category="electronics",
                latitude=37.7749,
                longitude=-122.4194,
                seller_id="e1",
            ),
        ]
    )
    resp = client.get(
        "/v1/listings?q=couch&latitude=37.7749&longitude=-122.4194&radius=5&category=furniture",
        headers={"X-App-Id": APP_ID},
    )
    assert resp.status_code == 200
    assert resp.json()["pagination"]["total"] == 1
    assert resp.json()["data"][0]["title"] == "SF couch"
    # distance_km present and in km
    assert resp.json()["data"][0]["distance_km"] is not None


def test_search_pagination_with_q():
    _seed([_row(title=f"Couch {i}", seller_id=f"s{i:02d}") for i in range(5)])
    r1 = client.get(
        "/v1/listings?q=couch&limit=2&offset=0", headers={"X-App-Id": APP_ID}
    )
    r2 = client.get(
        "/v1/listings?q=couch&limit=2&offset=2", headers={"X-App-Id": APP_ID}
    )
    assert r1.json()["pagination"]["total"] == 5
    assert r1.json()["pagination"]["has_more"] is True
    assert r2.json()["pagination"]["has_more"] is True
    r3 = client.get(
        "/v1/listings?q=couch&limit=2&offset=4", headers={"X-App-Id": APP_ID}
    )
    assert r3.json()["pagination"]["has_more"] is False


def test_top5_relevance_criterion_tdd_1_3():
    """TDD §1.3 top-5: for a query, top 5 results must contain q and title hits outrank description-only.

    Construct 10 listings: 5 with q in title, 5 with q only in description. Top 5 must be title hits.
    """
    rows: list[dict[str, Any]] = []
    for i in range(5):
        rows.append(
            _row(
                title=f"Stroller model {i}",
                description="Barely used",
                seller_id=f"title_{i}",
            )
        )
    for i in range(5):
        rows.append(
            _row(
                title=f"Unrelated {i}",
                description=f"This mentions stroller in description {i}",
                seller_id=f"desc_{i}",
            )
        )
    _seed(rows)

    resp = client.get("/v1/listings?q=stroller&limit=10", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 10
    top5 = data[:5]
    # All top5 must have stroller in title (title weight A)
    assert all("stroller" in d["title"].lower() for d in top5)
    # All 10 contain q somewhere, but bottom 5 are description-only
    assert all(
        "stroller" in (d["title"] + " " + d["description"]).lower() for d in data
    )
    # Schema conformance in search mode too
    for d in data:
        assert "seller_user_id" in d
        assert "distance_km" in d
        assert "actions" not in d


def test_search_seller_and_status_with_q():
    _seed(
        [
            _row(title="Couch active alice", seller_id="alice", status="active"),
            _row(title="Couch sold alice", seller_id="alice", status="sold"),
            _row(title="Couch active bob", seller_id="bob", status="active"),
        ]
    )
    r = client.get(
        "/v1/listings?q=couch&seller_user_id=alice", headers={"X-App-Id": APP_ID}
    )
    # default active-only
    assert r.json()["pagination"]["total"] == 1
    assert r.json()["data"][0]["seller_user_id"] == "alice"

    r2 = client.get(
        "/v1/listings?q=couch&seller_user_id=alice&status=sold",
        headers={"X-App-Id": APP_ID},
    )
    assert r2.json()["pagination"]["total"] == 1
    assert r2.json()["data"][0]["status"] == "sold"


def test_search_distance_km_always_km_even_with_mi_unit():
    _seed([_row(title="Near couch", latitude=37.7749, longitude=-122.4194)])
    resp = client.get(
        "/v1/listings?q=couch&latitude=37.7749&longitude=-122.4194&radius=1&unit=mi",
        headers={"X-App-Id": APP_ID},
    )
    assert resp.status_code == 200
    assert resp.json()["data"][0]["distance_km"] is not None
    assert resp.json()["data"][0]["distance_km"] < 2.0


def test_search_with_deterministic_seed_distribution():
    from seed import build_listings

    rng = random.Random(42)
    listings = build_listings(APP_ID, rng)
    session = SessionLocal()
    try:
        session.add_all(listings)
        session.commit()
    finally:
        session.close()

    # Query that should have hits in seeded data
    resp = client.get("/v1/listings?q=couch&limit=20", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 200
    # At least some results, and top 5 are relevant (contain couch in title/desc due to weighted vector)
    assert resp.json()["pagination"]["total"] > 0
    top5 = resp.json()["data"][:5]
    for d in top5:
        combined = (d["title"] + " " + d["description"]).lower()
        # Due to FTS stemming, couch should be in combined for top results
        assert "couch" in combined


def test_zero_spec_drift_openapi_has_unified_endpoint():
    # Export fragment and assert it matches PR1 contract: single path /v1/listings, no /search
    from export_openapi import build_fragment

    frag = build_fragment()
    assert "/v1/listings" in frag["paths"]
    assert "/v1/listings/search" not in frag["paths"], (
        "fragment should not export deprecated /search"
    )
    # Required query params per openapi/listings.yaml
    params = {p["name"] for p in frag["paths"]["/v1/listings"]["get"]["parameters"]}
    for required in [
        "q",
        "latitude",
        "longitude",
        "radius",
        "unit",
        "category",
        "condition",
        "price_min_cents",
        "price_max_cents",
        "seller_user_id",
        "status",
        "sort",
        "limit",
        "offset",
    ]:
        assert required in params, f"missing param {required} in generated fragment"
