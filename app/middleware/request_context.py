"""Request context — request_id ContextVar for error envelope."""

from __future__ import annotations

import contextvars

_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def current_request_id() -> str | None:
    return _request_id_ctx.get()


def set_request_id(request_id: str):
    return _request_id_ctx.set(request_id)


def reset_request_id(token):
    _request_id_ctx.reset(token)
