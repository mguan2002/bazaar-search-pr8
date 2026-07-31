"""Request dependencies.

`app_id` is injected here to mirror S2's auth middleware (API key + HMAC → app_id, §3.2).
This is a STUB for standalone development: it reads an `X-App-Id` header (default
"demo-app"). At merge time, delete this and depend on S2's real auth dependency — the
handlers and query layer are untouched because they only ever see a resolved `app_id`.
"""

from __future__ import annotations

from fastapi import Header


def get_app_id(x_app_id: str = Header(default="demo-app")) -> str:
    return x_app_id
