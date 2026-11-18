"""Bearer authentication and request ownership for optional HTTP transports."""

import hashlib
import re
import secrets
import time
from contextvars import ContextVar
from urllib.parse import parse_qs
from starlette.types import ASGIApp, Scope, Receive, Send, Message

CURRENT_OPERATOR: ContextVar[str] = ContextVar("capsolver_operator", default="local")


class BearerMiddleware:
    """Bind protocol sessions to authenticated operators before dispatching tools."""

    def __init__(self, app: ASGIApp, tokens: dict[str, str]) -> None:
        self.app = app
        self.tokens = tokens
        self.sessions: dict[str, tuple[str, float]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.tokens:
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = headers.get(b"authorization", b"")
        supplied = auth[7:] if auth[:7].lower() == b"bearer " else b""
        operator = next(
            (key for key, value in self.tokens.items() if secrets.compare_digest(supplied, value.encode("utf-8"))),
            None,
        )
        if operator is None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"www-authenticate", b"Bearer"), (b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"error":"Authentication required"}'})
            return
        namespace = hashlib.sha256(operator.encode()).hexdigest()
        now = time.monotonic()
        self.sessions = {k: v for k, v in self.sessions.items() if now - v[1] < 3600}
        query = parse_qs(scope.get("query_string", b"").decode("latin1"))
        session_id = headers.get(b"mcp-session-id", b"").decode("latin1") or query.get("session_id", [""])[0]
        if session_id and (session_id not in self.sessions or self.sessions[session_id][0] != namespace):
            await send({"type": "http.response.start", "status": 403, "headers": []})
            await send({"type": "http.response.body", "body": b"Session owner mismatch"})
            return
        if session_id:
            self.sessions[session_id] = (namespace, now)
        token = CURRENT_OPERATOR.set(namespace)
        event_prefix = bytearray()

        async def guarded_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                for key, value in message.get("headers", []):
                    if key.lower() == b"mcp-session-id":
                        self.sessions[value.decode("latin1")] = (namespace, time.monotonic())
            elif message["type"] == "http.response.body" and len(event_prefix) < 2048:
                event_prefix.extend(message.get("body", b"")[: 2048 - len(event_prefix)])
                matched = re.search(rb"session_id=([a-fA-F0-9-]{32,36})", event_prefix)
                if matched:
                    self.sessions[matched[1].decode()] = (namespace, time.monotonic())
            await send(message)

        try:
            await self.app(scope, receive, guarded_send)
        finally:
            CURRENT_OPERATOR.reset(token)
