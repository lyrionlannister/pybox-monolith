"""Rechazo de peticiones mutantes desde orígenes no permitidos (anti-CSRF)."""

import os

LOGIN = "/api/v1/auth/login"
_BODY = {"email": "nadie@example.com", "password": "Clave123!"}


class TestOriginCheckMiddleware:
    async def test_foreign_origin_is_rejected(self, client):
        resp = await client.post(
            LOGIN, json=_BODY, headers={"Origin": "https://evil.example.net"}
        )
        assert resp.status_code == 403

    async def test_allowed_origin_passes_through(self, client):
        allowed = os.environ["CORS_ORIGINS"].split(",")[0].strip()
        resp = await client.post(LOGIN, json=_BODY, headers={"Origin": allowed})
        assert resp.status_code != 403

    async def test_request_without_origin_passes_through(self, client):
        resp = await client.post(LOGIN, json=_BODY)
        assert resp.status_code != 403

    async def test_safe_methods_are_not_checked(self, client):
        resp = await client.get("/", headers={"Origin": "https://evil.example.net"})
        assert resp.status_code == 200
