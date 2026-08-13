"""PR9 — §3.6 validation matrix table-driven (one parametrized test per plan).

Covers all validation paths per openapi/listings.yaml:
 - q blank / too long / missing for search alias
 - latitude/longitude pairwise, out-of-range
 - radius <=0, >100 after conversion (km and mi)
 - unit invalid
 - category/condition/status/sort invalid
 - seller_user_id too long
 - price_min > price_max, negative price
 - limit/offset out of range
 - sort=relevance requires q (fragment rule)

All must return 400 validation_failed with envelope {error:{code,message,request_id}} and X-Request-Id echo.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal
from app.main import app
from app.models import Listing

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


def _assert_validation_failed(resp):
    assert resp.status_code == 400
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "validation_failed"
    assert "message" in body["error"]
    assert "request_id" in body["error"]
    assert body["error"]["request_id"] is not None
    assert "x-request-id" in resp.headers
    assert body["error"]["request_id"] == resp.headers["x-request-id"]


# Each tuple: query_string, description
VALIDATION_CASES = [
    ("latitude=37.7749", "lat without lng"),
    ("longitude=-122.4194", "lng without lat"),
    ("price_min_cents=500&price_max_cents=100", "price_min > price_max"),
    ("price_min_cents=-1", "negative price_min"),
    ("price_max_cents=-1", "negative price_max"),
    ("latitude=91&longitude=0", "lat out of range >90"),
    ("latitude=-91&longitude=0", "lat out of range <-90"),
    ("latitude=0&longitude=181", "lng out of range >180"),
    ("latitude=0&longitude=-181", "lng out of range <-180"),
    ("latitude=0&longitude=0&radius=0", "radius zero"),
    ("latitude=0&longitude=0&radius=-1", "radius negative"),
    ("latitude=0&longitude=0&radius=200", "radius 200km >100"),
    ("latitude=0&longitude=0&radius=70&unit=mi", "70mi=112km >100 after conversion"),
    ("unit=invalid", "invalid unit"),
    ("unit=KM", "unit case-sensitive (must be lower)"),
    ("category=invalid_cat", "invalid category"),
    ("condition=invalid_cond", "invalid condition"),
    ("status=invalid_status", "invalid status"),
    ("sort=invalid_sort", "invalid sort"),
    ("seller_user_id=" + "a" * 129, "seller_user_id too long >128"),
    ("limit=0", "limit zero"),
    ("limit=51", "limit >50"),
    ("offset=-1", "offset negative"),
    ("q=" + "a" * 201, "q too long >200"),
    ("q=%20%20", "q blank whitespace"),
    ("sort=relevance", "sort=relevance requires q"),
    # price range inverted already above, but also via q
    ("q=couch&price_min_cents=1000&price_max_cents=10", "price inverted with q"),
]


@pytest.mark.parametrize("query,desc", VALIDATION_CASES)
def test_validation_matrix(query, desc):
    resp = client.get(f"/v1/listings?{query}", headers={"X-App-Id": APP_ID})
    _assert_validation_failed(resp)


def test_q_blank_is_validation_failed():
    resp = client.get("/v1/listings?q=%20%20", headers={"X-App-Id": APP_ID})
    _assert_validation_failed(resp)


def test_search_alias_requires_q():
    resp = client.get("/v1/listings/search", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_failed"


def test_error_envelope_on_404():
    resp = client.get("/v1/does-not-exist", headers={"X-App-Id": APP_ID})
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "request_id" in body["error"]


def test_error_envelope_on_422_framework_validation():
    # FastAPI would normally return 422 for invalid float, but we map to 400 validation_failed
    resp = client.get(
        "/v1/listings?latitude=not-a-number", headers={"X-App-Id": APP_ID}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_failed"
