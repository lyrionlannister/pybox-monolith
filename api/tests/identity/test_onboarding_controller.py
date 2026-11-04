import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from identity.auth.models.verification_code_model import VerificationCodeModel
from identity.users.enums.user_enums import (
    IdentityVerificationStatus,
    UserRole,
    UserScope,
)
from messaging.providers.email_provider import NRS360EmailProvider
from tests.factories import get_user_by_email, register_payload

AUTH_BASE = "/api/v1/auth"
BASE = "/api/v1/onboarding"


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


@pytest.fixture
async def onboarding_user(client, db_session, auth_as, make_user_session_factory):
    """Registra un usuario deudor real y devuelve (client autenticado, user row, payload)."""
    payload = register_payload()
    resp = await client.post(f"{AUTH_BASE}/register/user", json=payload)
    assert resp.status_code == 201
    user = await get_user_by_email(db_session, payload["email"])
    session = make_user_session_factory(
        user_id=user.id, role=UserRole.USER, scope=UserScope.SELF
    )
    authed = auth_as(session)
    return authed, user, payload


class TestOnboardingStatus:
    async def test_status_valid(self, onboarding_user):
        authed, _user, _payload = onboarding_user
        resp = await authed.get(f"{BASE}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["phoneSet"] is True  # register/user exige phone_number
        assert body["emailVerified"] is False
        assert body["isComplete"] is False

    async def test_status_without_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/status")
        assert resp.status_code == 401


class TestRequestOtp:
    async def test_request_otp_valid(self, onboarding_user):
        authed, _user, _payload = onboarding_user
        with _mock_nrs360_email_success():
            resp = await authed.post(f"{BASE}/request-otp", json={"channel": "EMAIL"})
        assert resp.status_code == 204

    async def test_request_otp_invalid_channel_returns_422(self, onboarding_user):
        authed, _user, _payload = onboarding_user
        resp = await authed.post(f"{BASE}/request-otp", json={"channel": "WHATSAPP"})
        assert resp.status_code == 422

    async def test_request_otp_without_auth_returns_401(self, client):
        resp = await client.post(f"{BASE}/request-otp", json={"channel": "EMAIL"})
        assert resp.status_code == 401


class TestVerifyOtp:
    async def test_verify_otp_valid(self, onboarding_user, db_session):
        authed, user, _payload = onboarding_user
        await authed.post(f"{BASE}/request-otp", json={"channel": "EMAIL"})
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

        resp = await authed.post(
            f"{BASE}/verify-otp", json={"channel": "EMAIL", "code": code_row.code}
        )
        assert resp.status_code == 204

    async def test_verify_otp_wrong_code_returns_400(self, onboarding_user):
        authed, _user, _payload = onboarding_user
        await authed.post(f"{BASE}/request-otp", json={"channel": "EMAIL"})
        resp = await authed.post(
            f"{BASE}/verify-otp", json={"channel": "EMAIL", "code": "000000"}
        )
        assert resp.status_code == 400


class TestSetPassword:
    async def test_set_password_valid(self, onboarding_user):
        authed, _user, _payload = onboarding_user
        resp = await authed.patch(
            f"{BASE}/set-password", json={"new_password": "OtraFuerte1!"}
        )
        assert resp.status_code == 204

    async def test_set_password_weak_returns_422(self, onboarding_user):
        authed, _user, _payload = onboarding_user
        resp = await authed.patch(f"{BASE}/set-password", json={"new_password": "weak"})
        assert resp.status_code == 422


class TestSetPhone:
    async def test_set_phone_valid(self, onboarding_user):
        authed, _user, _payload = onboarding_user
        new_phone = f"+57{uuid.uuid4().int % 10**10:010d}"
        resp = await authed.patch(f"{BASE}/phone", json={"phone_number": new_phone})
        assert resp.status_code == 204

    async def test_set_phone_already_registered_returns_409(
        self, client, onboarding_user
    ):
        authed, _user, _payload = onboarding_user
        other = register_payload()
        await client.post(f"{AUTH_BASE}/register/user", json=other)
        resp = await authed.patch(
            f"{BASE}/phone", json={"phone_number": other["phone_number"]}
        )
        assert resp.status_code == 409


class TestUpdateProfile:
    async def test_update_profile_valid(self, onboarding_user):
        authed, _user, _payload = onboarding_user
        resp = await authed.patch(
            f"{BASE}/profile",
            json={
                "document_type": "CE",
                "document_number": str(uuid.uuid4().int)[:9],
                "nationality": "CO",
            },
        )
        assert resp.status_code == 204

    async def test_update_profile_document_not_valid_for_country_returns_400(
        self, onboarding_user
    ):
        authed, _user, _payload = onboarding_user
        resp = await authed.patch(
            f"{BASE}/profile",
            # RFC es un documento mexicano, no válido para nacionalidad CO
            json={
                "document_type": "RFC",
                "document_number": str(uuid.uuid4().int)[:9],
                "nationality": "CO",
            },
        )
        assert resp.status_code == 400

    async def test_update_profile_invalid_country_returns_400(self, onboarding_user):
        authed, _user, _payload = onboarding_user
        resp = await authed.patch(
            f"{BASE}/profile",
            json={
                "document_type": "CC",
                "document_number": str(uuid.uuid4().int)[:9],
                "nationality": "ZZ",
            },
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        "status_value",
        [IdentityVerificationStatus.PENDING, IdentityVerificationStatus.APPROVED],
    )
    async def test_cannot_change_document_after_identity_submitted(
        self, onboarding_user, db_session, status_value
    ):
        authed, user, _payload = onboarding_user
        original_hash = user.document_number_hash
        user.identity_verification_status = status_value
        await db_session.flush()
        resp = await authed.patch(
            f"{BASE}/profile",
            json={
                "document_type": "CC",
                "document_number": str(uuid.uuid4().int)[:9],
                "nationality": "CO",
            },
        )
        assert resp.status_code == 409
        await db_session.refresh(user)
        assert user.document_number_hash == original_hash
        assert user.identity_verification_status == status_value

    async def test_document_of_another_user_returns_409(
        self, client, onboarding_user, db_session
    ):
        authed, _user, _payload = onboarding_user
        other_payload = register_payload()
        resp = await client.post(f"{AUTH_BASE}/register/user", json=other_payload)
        assert resp.status_code == 201
        resp = await authed.patch(
            f"{BASE}/profile",
            json={
                "document_type": other_payload["document_type"],
                "document_number": other_payload["document_number"],
                "nationality": "CO",
            },
        )
        assert resp.status_code == 409

    async def test_denied_identity_resets_to_not_submitted_on_change(
        self, onboarding_user, db_session
    ):
        authed, user, _payload = onboarding_user
        user.identity_verification_status = IdentityVerificationStatus.DENIED
        await db_session.flush()
        resp = await authed.patch(
            f"{BASE}/profile",
            json={
                "document_type": "CC",
                "document_number": str(uuid.uuid4().int)[:9],
                "nationality": "CO",
            },
        )
        assert resp.status_code == 204
        await db_session.refresh(user)
        assert (
            user.identity_verification_status
            == IdentityVerificationStatus.NOT_SUBMITTED
        )
