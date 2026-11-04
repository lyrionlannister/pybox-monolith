from sqlalchemy import select

from core.security.constants.cookie_constants import (
    ACCESS_TOKEN_COOKIE,
    REFRESH_TOKEN_COOKIE,
)
from identity.auth.models.verification_code_model import VerificationCodeModel
from tests.factories import TEST_OTP_CODE, get_user_by_email, register_payload

AUTH_BASE = "/api/v1/auth"
ONBOARDING_BASE = "/api/v1/onboarding"
ORGS_BASE = "/api/v1/organizations/"


async def _fetch_otp_code(db_session, user_id) -> str:
    row = (
        (
            await db_session.execute(
                select(VerificationCodeModel)
                .where(VerificationCodeModel.user_id == user_id)
                .order_by(VerificationCodeModel.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    return TEST_OTP_CODE


async def _register(client, db_session):
    payload = register_payload()
    resp = await client.post(f"{AUTH_BASE}/register/user", json=payload)
    assert resp.status_code == 201
    user = await get_user_by_email(db_session, payload["email"])
    return user, payload


async def _verify_otp(client, db_session, user_id) -> None:
    await client.post(f"{ONBOARDING_BASE}/request-otp", json={"channel": "EMAIL"})
    code = await _fetch_otp_code(db_session, user_id)
    resp = await client.post(
        f"{ONBOARDING_BASE}/verify-otp", json={"channel": "EMAIL", "code": code}
    )
    assert resp.status_code == 204


class TestMfaGate:
    """Cubre core/security/dependencies.py (_require_mfa_verified): el token/cookie de
    acceso se emite completo desde el login, así que sin este gate cualquiera con la
    contraseña correcta tendría acceso de negocio sin pasar el segundo factor -- el
    MFA sería solo una pantalla de React, no un control real. Usa cookies reales (no
    `auth_as`) a propósito: `auth_as` pisa `get_session`/`get_pending_mfa_session`
    directo y no ejercita el gate."""

    async def test_business_endpoint_blocked_until_otp_verified(
        self, client, db_session
    ):
        user, _payload = await _register(client, db_session)

        blocked = await client.get(ORGS_BASE)
        assert blocked.status_code == 403

        # Onboarding debe seguir accesible mientras el MFA está pendiente: si no, un
        # usuario nuevo (mfa_habilitado=True por default) nunca podría completar el
        # propio flujo de onboarding que lo saca de "pendiente".
        status_resp = await client.get(f"{ONBOARDING_BASE}/status")
        assert status_resp.status_code == 200

        await _verify_otp(client, db_session, user.id)

        unlocked = await client.get(ORGS_BASE)
        assert unlocked.status_code == 200

    async def test_wrong_otp_code_keeps_endpoint_blocked(self, client, db_session):
        await _register(client, db_session)
        await client.post(f"{ONBOARDING_BASE}/request-otp", json={"channel": "EMAIL"})

        wrong = await client.post(
            f"{ONBOARDING_BASE}/verify-otp", json={"channel": "EMAIL", "code": "000000"}
        )
        assert wrong.status_code == 400

        still_blocked = await client.get(ORGS_BASE)
        assert still_blocked.status_code == 403

    async def test_fresh_login_requires_mfa_again(self, client, db_session):
        user, payload = await _register(client, db_session)
        await _verify_otp(client, db_session, user.id)
        assert (await client.get(ORGS_BASE)).status_code == 200

        login = await client.post(
            f"{AUTH_BASE}/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        assert login.status_code == 200

        blocked_again = await client.get(ORGS_BASE)
        assert blocked_again.status_code == 403

    async def test_token_refresh_does_not_re_lock(self, client, db_session):
        user, _payload = await _register(client, db_session)
        await _verify_otp(client, db_session, user.id)
        assert (await client.get(ORGS_BASE)).status_code == 200

        refresh_token = client.cookies.get(REFRESH_TOKEN_COOKIE)
        refreshed = await client.post(
            f"{AUTH_BASE}/refresh", json={"refresh_token": refresh_token}
        )
        assert refreshed.status_code == 200
        assert ACCESS_TOKEN_COOKIE in refreshed.cookies

        still_unlocked = await client.get(ORGS_BASE)
        assert still_unlocked.status_code == 200

    async def test_logout_clears_mfa_verification(self, client, db_session):
        user, payload = await _register(client, db_session)
        await _verify_otp(client, db_session, user.id)

        await client.post(f"{AUTH_BASE}/logout")

        login = await client.post(
            f"{AUTH_BASE}/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        assert login.status_code == 200
        assert (await client.get(ORGS_BASE)).status_code == 403
