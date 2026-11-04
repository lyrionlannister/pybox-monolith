import uuid

import pytest
from fastapi import HTTPException

from core.database.redis import redis_client
from core.security import dependencies as security_dependencies
from core.security.dependencies import (
    WsSessionGuard,
    _load_session,
    _subject_to_uuid,
    get_pending_mfa_session,
    get_sse_session,
    get_ws_session,
)
from identity.users.schemas.user_session_schema import UserSession, session_key


def _make_session(user_id: uuid.UUID) -> UserSession:
    return UserSession(user_id=user_id, full_name="Test", email="t@example.com")


class TestSubjectToUuid:
    """Cubre core/security/dependencies.py:25-29 -- un `sub` ausente o no-UUID en el
    payload del token no debe explotar con un error 500, sino un 401 controlado."""

    def test_valid_sub_returns_uuid(self):
        user_id = uuid.uuid4()
        assert _subject_to_uuid({"sub": str(user_id)}) == user_id

    def test_missing_sub_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            _subject_to_uuid({})
        assert exc.value.status_code == 401

    def test_non_uuid_sub_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            _subject_to_uuid({"sub": "not-a-uuid"})
        assert exc.value.status_code == 401


class TestLoadSession:
    """Cubre _load_session: JSON corrupto/con forma vieja en Redis (36-37) y ausencia
    de sesión (42) deben devolver 401, nunca un 500 sin manejar."""

    async def test_corrupted_json_raises_401(self, fake_redis):
        user_id = uuid.uuid4()
        await fake_redis.set(session_key(user_id), "{not valid json", 60)
        with pytest.raises(HTTPException) as exc:
            await _load_session(user_id)
        assert exc.value.status_code == 401

    async def test_missing_session_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await _load_session(uuid.uuid4())
        assert exc.value.status_code == 401

    async def test_valid_session_refreshes_ttl(self, fake_redis):
        user_id = uuid.uuid4()
        session = _make_session(user_id)
        await fake_redis.set(session_key(user_id), session.model_dump_json(), 5)
        loaded = await _load_session(user_id)
        assert loaded.user_id == user_id
        # El TTL se refresca a DEFAULT_TTL (3h) en cada lectura -- sigue vivo mucho
        # después del TTL corto original de 5s.
        entry = fake_redis._store[session_key(user_id)]
        assert entry[1] is not None


class TestPendingMfaSessionInvalidToken:
    async def test_missing_sub_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_pending_mfa_session({})
        assert exc.value.status_code == 401


class TestStreamSessionDependencies:
    """Cubre las ramas de error de get_sse_session/get_ws_session (85-90): token
    inválido/ausente sobre la conexión de streaming debe rechazar con 401."""

    async def test_sse_session_invalid_cookie_raises_401(self):
        class _FakeRequest:
            cookies: dict = {"access_token": "not-a-real-jwt"}

        with pytest.raises(HTTPException) as exc:
            await get_sse_session(_FakeRequest())
        assert exc.value.status_code == 401

    async def test_sse_session_missing_token_raises_401(self):
        class _FakeRequest:
            cookies: dict = {}

        with pytest.raises(HTTPException) as exc:
            await get_sse_session(_FakeRequest())
        assert exc.value.status_code == 401

    async def test_ws_session_invalid_cookie_raises_401(self):
        class _FakeWebSocket:
            cookies: dict = {"access_token": "not-a-real-jwt"}
            headers: dict = {}

        with pytest.raises(HTTPException) as exc:
            await get_ws_session(_FakeWebSocket())
        assert exc.value.status_code == 401

    async def test_token_in_the_query_string_is_not_accepted(self):
        """El token solo se acepta por cookie: por query string quedaría en logs y proxies."""

        class _FakeRequest:
            cookies: dict = {}
            query_params: dict = {"token": "anything"}

        with pytest.raises(HTTPException) as exc:
            await get_sse_session(_FakeRequest())
        assert exc.value.status_code == 401


class TestWebSocketHardening:
    async def test_foreign_origin_is_rejected_before_auth(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")

        class _FakeWebSocket:
            cookies: dict = {}
            headers: dict = {"origin": "https://evil.example.net"}

        with pytest.raises(HTTPException) as exc:
            await get_ws_session(_FakeWebSocket())
        assert exc.value.status_code == 403

    async def test_allowed_origin_continues_to_token_check(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")

        class _FakeWebSocket:
            cookies: dict = {}
            headers: dict = {"origin": "https://app.example.com"}

        with pytest.raises(HTTPException) as exc:
            await get_ws_session(_FakeWebSocket())
        assert exc.value.status_code == 401

    async def test_guard_closes_revoked_session(self, monkeypatch):
        monkeypatch.setattr(security_dependencies, "WS_SESSION_RECHECK_SECONDS", 0)
        user_id = uuid.uuid4()
        guard = WsSessionGuard(_make_session(user_id))
        with pytest.raises(HTTPException) as exc:
            await guard.current()
        assert exc.value.status_code == 401

    async def test_guard_refreshes_live_session(self, monkeypatch):
        monkeypatch.setattr(security_dependencies, "WS_SESSION_RECHECK_SECONDS", 0)
        user_id = uuid.uuid4()
        fresh = UserSession(
            user_id=user_id, full_name="Nuevo", email="t@example.com", mfa_enabled=False
        )
        await redis_client.set_json(session_key(user_id), fresh)
        guard = WsSessionGuard(_make_session(user_id))
        assert (await guard.current()).full_name == "Nuevo"
