"""Middleware anti-CSRF: rechaza peticiones mutantes desde orígenes no permitidos."""

import json
from typing import Any, Awaitable, Callable

from core.tools.config_tools import get_or_throw

ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OriginCheckMiddleware:
    """La sesión viaja en cookies `SameSite=Lax`, que el navegador sí adjunta a
    peticiones desde subdominios del mismo sitio (landing, pgAdmin): si una de esas
    páginas queda comprometida podría operar con la sesión de la víctima. Los
    navegadores siempre mandan `Origin` en peticiones mutantes, así que basta con
    exigir que, si viene, sea uno de `CORS_ORIGINS`. Sin `Origin` no es un navegador
    (webhooks, n8n, clientes de API) y no aplica."""

    def __init__(self, app) -> None:
        self.app = app
        self._allowed = {
            o.strip() for o in get_or_throw("CORS_ORIGINS").split(",") if o.strip()
        }

    async def __call__(self, scope: dict, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _MUTATING_METHODS:
            await self.app(scope, receive, send)
            return
        origin = next(
            (
                v.decode("latin-1")
                for k, v in scope.get("headers", [])
                if k == b"origin"
            ),
            None,
        )
        if origin is None or origin in self._allowed:
            await self.app(scope, receive, send)
            return
        body = json.dumps({"error": "Origen no permitido."}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
