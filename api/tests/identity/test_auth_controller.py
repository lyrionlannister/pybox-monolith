import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from identity.auth.enums.auth_enums import AuthProvider
from identity.auth.enums.notification_enums import VerificationChannel
from identity.auth.models.verification_code_model import VerificationCodeModel
from identity.auth.services.oauth_provider_service import (
    OAuthProviderService,
    ProviderProfile,
)
from identity.users.enums.user_enums import UserRole, UserScope
from messaging.providers.email_provider import NRS360EmailProvider
from tests.factories import (
    STRONG_PASSWORD,
    get_user_by_email,
    register_payload,
    unique_document_number,
    unique_email,
)

BASE = "/api/v1/auth"


def _mock_nrs360_email_success():
    """`NRS360EmailProvider` es un singleton que hace un POST real a 360nrs.com
    (ver email_provider.py); en CI las credenciales son dummies no-secretas, así
    que sin este mock el envío falla con 401 real del proveedor. Mismo patrón que
    tests/messaging/providers/test_sms_provider.py: se reemplaza `_http`."""
    response = httpx.Response(
        status_code=200,
        content=json.dumps({"result": [], "sendingId": 1}).encode(),
        request=httpx.Request("POST", "https://dashboard.360nrs.com/api/rest/mailing"),
    )
    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=response)
    return patch.object(NRS360EmailProvider(), "_http", mock_http)


# ---------------------------------------------------------------------------
# POST /register (admin) y /register/user
# ---------------------------------------------------------------------------
class TestRegister:
    async def test_register_admin_valid(self, client):
        resp = await client.post(f"{BASE}/register", json=register_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body["tokenType"] == "Bearer"
        assert body["authProvider"] == "PROPIO"
        # access_token/refresh_token viajan solo como cookie httpOnly, nunca en el body
        assert "access_token" not in body
        assert "access_token" in resp.cookies

    async def test_register_user_scope_self(self, client, db_session):
        payload = register_payload()
        resp = await client.post(f"{BASE}/register/user", json=payload)
        assert resp.status_code == 201
        user = await get_user_by_email(db_session, payload["email"])
        assert user.email == payload["email"].lower()

    async def test_register_weak_password_returns_422(self, client):
        resp = await client.post(
            f"{BASE}/register", json=register_payload(password="weak")
        )
        assert resp.status_code == 422

    async def test_register_duplicate_email_returns_400(self, client):
        payload = register_payload()
        first = await client.post(f"{BASE}/register", json=payload)
        assert first.status_code == 201
        second = await client.post(
            f"{BASE}/register", json=register_payload(email=payload["email"])
        )
        assert second.status_code == 400

    async def test_register_invalid_country_returns_400(self, client):
        resp = await client.post(
            f"{BASE}/register", json=register_payload(nationality="ZZ")
        )
        assert resp.status_code == 400

    async def test_register_missing_required_field_returns_422(self, client):
        payload = register_payload()
        del payload["email"]
        resp = await client.post(f"{BASE}/register", json=payload)
        assert resp.status_code == 422

    async def test_register_invalid_email_format_returns_422(self, client):
        resp = await client.post(
            f"{BASE}/register", json=register_payload(email="not-an-email")
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------
class TestLogin:
    async def test_login_valid(self, client):
        payload = register_payload()
        await client.post(f"{BASE}/register", json=payload)
        resp = await client.post(
            f"{BASE}/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.cookies

    async def test_login_wrong_password_returns_400(self, client):
        payload = register_payload()
        await client.post(f"{BASE}/register", json=payload)
        resp = await client.post(
            f"{BASE}/login", json={"email": payload["email"], "password": "OtraClave1!"}
        )
        assert resp.status_code == 400

    async def test_login_unknown_email_returns_400(self, client):
        resp = await client.post(
            f"{BASE}/login", json={"email": unique_email(), "password": STRONG_PASSWORD}
        )
        assert resp.status_code == 400

    async def test_login_invalid_body_returns_422(self, client):
        resp = await client.post(f"{BASE}/login", json={"email": "not-an-email"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /oauth, /oauth/user, /oauth/login
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_google_profile(monkeypatch):
    """Evita llamar a Google real: parcha el método a nivel de clase, así
    cualquier instancia que AuthService cree por request queda cubierta."""

    def _apply(
        email: str | None = None, provider_user_id: str | None = None
    ) -> ProviderProfile:
        profile = ProviderProfile(
            provider=AuthProvider.GOOGLE,
            provider_user_id=provider_user_id or uuid.uuid4().hex,
            email=email or unique_email(),
            email_verified=True,
            firstname="Google",
            lastname="User",
        )
        monkeypatch.setattr(
            OAuthProviderService,
            "verify_provider_token",
            lambda self, provider, token: profile,
        )
        return profile

    return _apply


class TestOAuth:
    async def test_oauth_register_admin_valid(self, client, fake_google_profile):
        fake_google_profile()
        resp = await client.post(
            f"{BASE}/oauth", json={"provider": "GOOGLE", "token": "fake-token"}
        )
        assert resp.status_code == 200
        assert "access_token" in resp.cookies

    async def test_oauth_register_existing_account_returns_400(
        self, client, fake_google_profile
    ):
        profile = fake_google_profile()
        first = await client.post(
            f"{BASE}/oauth", json={"provider": "GOOGLE", "token": "fake-token"}
        )
        assert first.status_code == 200
        # mismo email/provider_user_id -> ya existe, register debe rechazar
        monkeypatch_reapply = fake_google_profile(
            email=profile.email, provider_user_id=profile.provider_user_id
        )
        second = await client.post(
            f"{BASE}/oauth", json={"provider": "GOOGLE", "token": "fake-token"}
        )
        assert second.status_code == 400

    async def test_oauth_unsupported_provider_returns_400(self, client):
        resp = await client.post(
            f"{BASE}/oauth", json={"provider": "FACEBOOK", "token": "whatever"}
        )
        assert resp.status_code == 400

    async def test_oauth_missing_token_returns_422(self, client):
        resp = await client.post(f"{BASE}/oauth", json={"provider": "GOOGLE"})
        assert resp.status_code == 422

    async def test_oauth_login_valid(self, client, fake_google_profile):
        fake_google_profile()
        register = await client.post(
            f"{BASE}/oauth", json={"provider": "GOOGLE", "token": "fake-token"}
        )
        assert register.status_code == 200
        login = await client.post(
            f"{BASE}/oauth/login", json={"provider": "GOOGLE", "token": "fake-token"}
        )
        assert login.status_code == 200

    async def test_oauth_login_unknown_account_returns_400(
        self, client, fake_google_profile
    ):
        fake_google_profile()
        resp = await client.post(
            f"{BASE}/oauth/login", json={"provider": "GOOGLE", "token": "fake-token"}
        )
        assert resp.status_code == 400

    async def test_oauth_endpoints_are_rate_limited(self, client):
        """/oauth y /oauth/login no tenían límite de intentos (a diferencia de
        /login), pese al comentario del router que dice que todos los endpoints
        sensibles a fuerza bruta lo llevan -- ver auth_controller.py."""
        for _ in range(20):
            resp = await client.post(
                f"{BASE}/oauth", json={"provider": "FACEBOOK", "token": "x"}
            )
            assert resp.status_code == 400
        limited = await client.post(
            f"{BASE}/oauth", json={"provider": "FACEBOOK", "token": "x"}
        )
        assert limited.status_code == 429


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------
class TestRefresh:
    async def test_refresh_valid(self, client):
        payload = register_payload()
        await client.post(f"{BASE}/register", json=payload)
        resp = await client.post(f"{BASE}/refresh")
        assert resp.status_code == 200
        assert "access_token" in resp.cookies

    async def test_refresh_without_token_returns_401(self, client):
        resp = await client.post(f"{BASE}/refresh")
        assert resp.status_code == 401

    async def test_refresh_invalid_token_returns_400_or_401(self, client):
        resp = await client.post(f"{BASE}/refresh", json={"refresh_token": "not-a-jwt"})
        assert resp.status_code in (400, 401)


# ---------------------------------------------------------------------------
# POST /logout, /logout/{user_id}
# ---------------------------------------------------------------------------
class TestLogout:
    async def test_logout_valid(self, client):
        payload = register_payload()
        await client.post(f"{BASE}/register", json=payload)
        resp = await client.post(f"{BASE}/logout")
        assert resp.status_code == 200

    async def test_logout_without_auth_returns_401(self, client):
        resp = await client.post(f"{BASE}/logout")
        assert resp.status_code == 401

    async def test_force_logout_valid_as_global_admin(
        self, client, db_session, auth_as, make_user_session_factory
    ):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        target = await get_user_by_email(db_session, payload["email"])

        admin_session = make_user_session_factory(
            role=UserRole.ADMIN, scope=UserScope.GLOBAL
        )
        authed = auth_as(admin_session)
        resp = await authed.post(f"{BASE}/logout/{target.id}")
        assert resp.status_code == 200

    async def test_force_logout_self_returns_400(
        self, client, auth_as, make_user_session_factory
    ):
        session = make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        authed = auth_as(session)
        resp = await authed.post(f"{BASE}/logout/{session.user_id}")
        assert resp.status_code == 400

    async def test_force_logout_forbidden_for_unrelated_self_scope(
        self, client, db_session, auth_as, make_user_session_factory
    ):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        target = await get_user_by_email(db_session, payload["email"])

        unrelated_session = make_user_session_factory(
            role=UserRole.USER, scope=UserScope.SELF
        )
        authed = auth_as(unrelated_session)
        resp = await authed.post(f"{BASE}/logout/{target.id}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /change-password
# ---------------------------------------------------------------------------
class TestChangePassword:
    async def test_change_password_valid(
        self, client, db_session, auth_as, make_user_session_factory
    ):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        user = await get_user_by_email(db_session, payload["email"])

        session = make_user_session_factory(
            user_id=user.id, role=UserRole.USER, scope=UserScope.SELF
        )
        authed = auth_as(session)
        resp = await authed.post(
            f"{BASE}/change-password",
            json={
                "current_password": payload["password"],
                "new_password": "OtraFuerte1!",
            },
        )
        assert resp.status_code == 204

    async def test_change_password_wrong_current_returns_400(
        self, client, db_session, auth_as, make_user_session_factory
    ):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        user = await get_user_by_email(db_session, payload["email"])

        session = make_user_session_factory(
            user_id=user.id, role=UserRole.USER, scope=UserScope.SELF
        )
        authed = auth_as(session)
        resp = await authed.post(
            f"{BASE}/change-password",
            json={"current_password": "Incorrecta1!", "new_password": "OtraFuerte1!"},
        )
        assert resp.status_code == 400

    async def test_change_password_weak_new_password_returns_422(
        self, client, db_session, auth_as, make_user_session_factory
    ):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        user = await get_user_by_email(db_session, payload["email"])

        session = make_user_session_factory(
            user_id=user.id, role=UserRole.USER, scope=UserScope.SELF
        )
        authed = auth_as(session)
        resp = await authed.post(
            f"{BASE}/change-password",
            json={"current_password": payload["password"], "new_password": "weak"},
        )
        assert resp.status_code == 422

    async def test_change_password_without_auth_returns_401(self, client):
        resp = await client.post(
            f"{BASE}/change-password",
            json={"current_password": "x", "new_password": "OtraFuerte1!"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Forgot-password: lookup -> send-code -> verify-code -> reset-password
# ---------------------------------------------------------------------------
class TestForgotPassword:
    async def test_lookup_valid_returns_masked_contact(self, client, db_session):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        resp = await client.post(
            f"{BASE}/forgot-password/lookup",
            json={
                "document_type": payload["document_type"],
                "document_number": payload["document_number"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["maskedEmail"] is not None

    async def test_lookup_unknown_document_returns_uniform_empty_response(self, client):
        resp = await client.post(
            f"{BASE}/forgot-password/lookup",
            json={"document_type": "CC", "document_number": unique_document_number()},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"maskedEmail": None, "maskedPhone": None}

    async def test_send_code_valid(self, client):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        with _mock_nrs360_email_success():
            resp = await client.post(
                f"{BASE}/forgot-password/send-code",
                json={
                    "document_type": payload["document_type"],
                    "document_number": payload["document_number"],
                    "channel": "EMAIL",
                },
            )
        assert resp.status_code == 204

    async def test_send_code_unknown_document_returns_204_without_sending(self, client):
        # Mismo criterio que el lookup (paso 1): respuesta uniforme exista o no la
        # cuenta, para no servir de oráculo de documentos registrados.
        resp = await client.post(
            f"{BASE}/forgot-password/send-code",
            json={
                "document_type": "CC",
                "document_number": unique_document_number(),
                "channel": "EMAIL",
            },
        )
        assert resp.status_code == 204

    async def test_verify_code_valid(self, client, db_session):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        await client.post(
            f"{BASE}/forgot-password/send-code",
            json={
                "document_type": payload["document_type"],
                "document_number": payload["document_number"],
                "channel": "EMAIL",
            },
        )
        user = await get_user_by_email(db_session, payload["email"])
        code_row = (
            (
                await db_session.execute(
                    select(VerificationCodeModel)
                    .where(VerificationCodeModel.user_id == user.id)
                    .order_by(VerificationCodeModel.created_at.desc())
                )
            )
            .scalars()
            .first()
        )

        resp = await client.post(
            f"{BASE}/forgot-password/verify-code",
            json={
                "document_type": payload["document_type"],
                "document_number": payload["document_number"],
                "code": code_row.code,
                "channel": "EMAIL",
            },
        )
        assert resp.status_code == 204

    async def test_verify_code_wrong_code_returns_400(self, client):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        await client.post(
            f"{BASE}/forgot-password/send-code",
            json={
                "document_type": payload["document_type"],
                "document_number": payload["document_number"],
                "channel": "EMAIL",
            },
        )
        resp = await client.post(
            f"{BASE}/forgot-password/verify-code",
            json={
                "document_type": payload["document_type"],
                "document_number": payload["document_number"],
                "code": "000000",
                "channel": "EMAIL",
            },
        )
        assert resp.status_code == 400

    async def test_reset_password_valid(self, client, db_session):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        await client.post(
            f"{BASE}/forgot-password/send-code",
            json={
                "document_type": payload["document_type"],
                "document_number": payload["document_number"],
                "channel": "EMAIL",
            },
        )
        user = await get_user_by_email(db_session, payload["email"])
        code_row = (
            (
                await db_session.execute(
                    select(VerificationCodeModel)
                    .where(VerificationCodeModel.user_id == user.id)
                    .order_by(VerificationCodeModel.created_at.desc())
                )
            )
            .scalars()
            .first()
        )

        resp = await client.post(
            f"{BASE}/reset-password",
            json={
                "document_type": payload["document_type"],
                "document_number": payload["document_number"],
                "code": code_row.code,
                "channel": "EMAIL",
                "new_password": "OtraFuerte1!",
            },
        )
        assert resp.status_code == 204

        login = await client.post(
            f"{BASE}/login",
            json={"email": payload["email"], "password": "OtraFuerte1!"},
        )
        assert login.status_code == 200

    async def test_reset_password_weak_new_password_returns_422(self, client):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        resp = await client.post(
            f"{BASE}/reset-password",
            json={
                "document_type": payload["document_type"],
                "document_number": payload["document_number"],
                "code": "123456",
                "channel": "EMAIL",
                "new_password": "weak",
            },
        )
        assert resp.status_code == 422

    async def test_reset_password_invalid_code_returns_400(self, client):
        payload = register_payload()
        await client.post(f"{BASE}/register/user", json=payload)
        resp = await client.post(
            f"{BASE}/reset-password",
            json={
                "document_type": payload["document_type"],
                "document_number": payload["document_number"],
                "code": "000000",
                "channel": "EMAIL",
                "new_password": "OtraFuerte1!",
            },
        )
        assert resp.status_code == 400
