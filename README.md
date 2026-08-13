# Bazaar Search & Discovery — P3 standalone slice

A self-contained implementation of the Bazaar **Search & Discovery** subsystem (browse +
full-text search over listings), built ahead of the other tracks so P3 isn't blocked
waiting on S1/S2/P1/P2. It runs against a local Docker Postgres and is structured so the
eventual integration into S2's service is a **re-point + drop-in**, not a rewrite.

Design doc: *Bazaar Search & Discovery — Technical Design Doc* (§ references below map to it).

## Quickstart

```bash
uv sync
docker compose up -d                 # local Postgres 16 on host port 5433
cp .env.example .env
uv run alembic upgrade head          # create listings table + search_vector + indexes (§3.1)
uv run python seed.py --reset        # 150 listings, category/geo mix (§4.4)
uv run uvicorn app.main:app --reload # http://127.0.0.1:8000/docs
uv run python export_openapi.py      # -> openapi/listings.json (hand to P2)
```

## Endpoints (§3.2, PR1 fragment T282737844, PR8 T282737884)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/v1/listings` | **Unified** browse + search (single endpoint, no separate `/search`). `q` optional — presence flips default sort newest→relevance. Filters: geo (`latitude/longitude/radius+unit=km|mi`), category/condition/price, `seller_user_id` + `status` (single-value, default active). Offset pagination, `distance_km` projected when geo supplied, always km regardless of `unit`. |

`app_id` is injected by the auth layer (header `X-App-Id` in this stub), **never** a query
param. Ranking is orthogonal — geo is always a filter, never a sort (§3.4). Newest first
for browse, `ts_rank` relevance for search (title weight A > description B).
Errors use S2 middleware envelope `{error:{code,message,request_id}}` (T283279748) with `X-Request-Id` header. Deprecated `GET /v1/listings/search` kept as slice-only alias (not exported).

## What's here

| File | Role | Design doc |
| --- | --- | --- |
| `migrations/versions/0001_listings_search.py` | `search_vector` generated column + GIN/browse/geo indexes | §3.1 |
| `app/models.py` | `Listing` ORM model (provisional contract) | §2.1 |
| `app/geo.py` | Bounding-box helper (pure arithmetic, no PostGIS) | §5.2 |
| `app/search.py` | Browse + search query builders, ranking | §3.3, §3.4 |
| `app/routes_listings.py` | Endpoints, validation, error contract | §3.2, §3.6 |
| `app/deps.py` | Stub `app_id` auth dependency (mirrors S2 middleware) | §3.2 |
| `app/schemas.py` | `ListingResponse` / pagination envelope | §3.2 |
| `seed.py` | 150-listing demo dataset | §4.4 |
| `export_openapi.py` | Emits `openapi/listings.json` for P2/P1 | §1.3, §2.1 |

## Provisional contracts — reconcile with the pod

These are P3's best guess at other tracks' interfaces; a mismatch later is a small,
localized change (see merge path). Flag them in the pod channel:

- **`listings` table** (`app/models.py`, migration): owned by **S2** (T282737576). The
  base columns are provisional; **the `search_vector` column + 4 indexes are P3's
  contribution** — hand the migration to S2.
- **`ListingResponse` shape** (`app/schemas.py`): owned by **P2**. Reconcile exact fields,
  esp. image handling (design doc §9 Q3).
- **`category` enum values** (`app/models.py::CATEGORIES`): owned by **P2** (§9 Q2).

## Merge path (when the real tracks land)

| When | Action | Effort |
| --- | --- | --- |
| S1 Postgres live | Point `DATABASE_URL` at the managed instance | 1 line |
| S2 `listings` table exists | Contribute the §3.1 migration; drop the provisional base-table half | small |
| S2 auth middleware exists | Replace `app/deps.py::get_app_id` with S2's real dependency | 1 import |
| P2 owns the OpenAPI spec | Merge `openapi/listings.json`; reconcile `ListingResponse` | small |
| P1 SDK published | Demo app swaps `fetch()` for the SDK (§4.5) | small |
| S1 Redis live | Add a Redis cache impl behind the browse path (§3.5) | small |

## Verified behavior (PR8)

- Unified `GET /v1/listings` with optional `q`, offset pagination, `has_more` stable (total order `created_at DESC, id DESC`)
- Browse mode: recency-first + price_asc/desc, geo bounding-box + haversine exact (13km SF→Oakland trimmed), `distance_km` projected, `unit=km|mi` conversion (mi→km server-side)
- Filters: category/condition/price_min/max inclusive, `seller_user_id` + `status` single-value (default active-only), validated enums
- Search mode (basic): `q` → `plainto_tsquery` + `ts_rank` title A > description B, relevance default when `q` present, newest default when absent
- Error contract: `{error:{code,message,request_id}}` with `X-Request-Id` echoed, validation `code=validation_failed` → 400, `search_unavailable` → 503
- Schema conformance: `seller_user_id` (not `seller_id`), `distance_km` present when geo supplied else null, no `actions[]` on list
- Tests: 35 passed — 12 geo unit (mi→km, bbox, haversine, finite guards) + 23 browse integration vs seeded fixtures (150 listings seed=42, pagination, filters, geo, mi conversion, seller/status, validation shape)

## Not yet done (next PRs)

- **PR9** search mode §3.6 validation matrix + relevance/conformance tests (top-5 criterion TDD §1.3, zero spec drift)
- **PR10** seed CLI + CRUD insertion + smoke test (images to MinIO path)
- **PR11** 100K loader + EXPLAIN pass + p95 RESULTS.md
- Reference demo app, cold-tester protocol, Redis caching (§3.5) — out of scope per P3 plan
