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

## Endpoints (§3.2)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/v1/listings` | Browse; recency-first; geo/category/condition/price filters; offset pagination |
| GET | `/v1/listings/search` | Full-text search (`q` required); relevance-first (`ts_rank`), recency tie-break |

`app_id` is injected by the auth layer (header `X-App-Id` in this stub), **never** a query
param. Ranking is simple and orthogonal — geo is always a filter, never a sort (§3.4).
Errors use the flat `{"error": "..."}` envelope from §3.6.

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

## Verified behavior (smoke-tested)

Browse (recency + filters + price sort), full-text search (title weight A ranks above
description weight B), geo bounding-box filter, offset pagination (`has_more`), and the
full §3.6 error contract (400 missing `q`; 422 bad radius/geo/enum; 200 empty).

## Not yet done

- **Automated tests (§7).** Blocked by this environment's provenance guardrail
  (unit-test assertions are 1P-only). To be authored by a 1P model / human. Behavior is
  currently verified via manual smoke tests.
- **Reference demo app** (Vite/React/Tailwind, §4) and **cold-tester protocol** (§4.1) —
  next steps; the API + `openapi/listings.json` are ready to build against.
- **Redis caching** (§3.5) — seam noted; add when S1's Redis is available.
