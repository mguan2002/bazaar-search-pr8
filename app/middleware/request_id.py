"""Request ID middleware — outermost, per bazaar-p3 reference.

- Reads inbound X-Request-Id (validated length/charset) else mints req_<12 hex>
- Binds to ContextVar for error envelope
- Echoes on X-Request-Id response header
- Emits 500 envelope itself for bare exceptions so request_id survives
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middleware.request_context import (
    current_request_id,
    reset_request_id,
    set_request_id,
)

REQUEST_ID_HEADER = b"x-request-id"
MAX_REQUEST_ID_LEN = 64
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


def _build_envelope(code: str, message: str) -> dict:
    return {
        "error": {"code": code, "message": message, "request_id": current_request_id()}
    }


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = self._resolve_incoming(scope)
        token = set_request_id(incoming)
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = [
                    (n, v)
                    for n, v in message.get("headers", [])
                    if n != REQUEST_ID_HEADER
                ]
                headers.append((REQUEST_ID_HEADER, incoming.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            if response_started:
                raise
            body = json.dumps(
                _build_envelope("internal_error", "internal server error")
            ).encode()
            await send_with_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send_with_id({"type": "http.response.body", "body": body})
        finally:
            reset_request_id(token)

    @staticmethod
    def _resolve_incoming(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name == REQUEST_ID_HEADER:
                try:
                    inbound = value.decode().strip()
                except Exception:
                    break
                if (
                    inbound
                    and len(inbound) <= MAX_REQUEST_ID_LEN
                    and _REQUEST_ID_RE.match(inbound)
                ):
                    return inbound
                break
        return f"req_{uuid.uuid4().hex[:12]}"
