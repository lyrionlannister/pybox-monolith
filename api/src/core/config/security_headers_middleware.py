"""Middleware que agrega headers de seguridad estándar a cada respuesta."""

from typing import Any, Awaitable, Callable

from core.tools.config_tools import get_or_throw

ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]

_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
]
_HSTS_HEADER = (b"strict-transport-security", b"max-age=63072000; includeSubDomains")


class SecurityHeadersMiddleware:
    """ASGI puro (mismo motivo que `LoggingMiddleware`): agrega headers en
    `send_wrapper` sin interceptar el stream de respuesta."""

    def __init__(self, app) -> None:
        self.app = app
        self._is_production = get_or_throw("ENV") == "production"

    async def __call__(self, scope: dict, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: ASGIMessage) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(_HEADERS)
                if self._is_production:
                    headers.append(_HSTS_HEADER)
            await send(message)

        await self.app(scope, receive, send_wrapper)
