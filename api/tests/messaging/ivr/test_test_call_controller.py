"""Autorización de la llamada de prueba IVR (cuenta de Helena compartida)."""

import uuid
from unittest.mock import AsyncMock

import pytest

from core.security.constants.permissions import PORTFOLIO_COMMUNICATIONS
from identity.organizations.enums.organization_enums import VerificationStatus
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_session_schema import OrgSessionEntry
from main import app as fastapi_app
from messaging.ivr.controllers.test_call_controller import TEST_CALLS_PER_HOUR
from messaging.ivr.dependencies import get_helena_client
from tests.receivables.conftest import build_organization, build_portfolio

BASE = "/api/v1/ivr/test-call/"


@pytest.fixture
def helena_mock():
    client = AsyncMock()
    client.send_unique = AsyncMock(return_value={"ok": True})
    fastapi_app.dependency_overrides[get_helena_client] = lambda: client
    yield client
    fastapi_app.dependency_overrides.pop(get_helena_client, None)


async def _portfolio(db_session, **org_overrides):
    org = build_organization(**org_overrides)
    db_session.add(org)
    await db_session.flush()
    portfolio = build_portfolio(org.id)
    db_session.add(portfolio)
    await db_session.flush()
    return org, portfolio


def _body(portfolio_id) -> dict:
    return {"phone": "3001234567", "config": {}, "portfolioId": str(portfolio_id)}


def _member(make_user_session_factory, org_id, role=UserRole.ADMIN):
    return make_user_session_factory(
        role=None,
        scope=UserScope.ORGANIZATION,
        orgs={
            str(org_id): OrgSessionEntry(
                role=role,
                org_name="Org",
                permissions=frozenset({PORTFOLIO_COMMUNICATIONS}),
                verification_status=VerificationStatus.APPROVED,
            )
        },
    )


class TestTestCallAuthorization:
    async def test_member_of_another_org_gets_404(
        self, db_session, auth_as, make_user_session_factory, helena_mock
    ):
        _org, portfolio = await _portfolio(db_session)
        authed = auth_as(_member(make_user_session_factory, uuid.uuid4()))
        resp = await authed.post(BASE, json=_body(portfolio.id))
        assert resp.status_code == 404
        helena_mock.send_unique.assert_not_called()

    async def test_member_without_portfolio_grant_gets_403(
        self, db_session, auth_as, make_user_session_factory, helena_mock
    ):
        org, portfolio = await _portfolio(db_session)
        authed = auth_as(_member(make_user_session_factory, org.id, role=UserRole.USER))
        resp = await authed.post(BASE, json=_body(portfolio.id))
        assert resp.status_code == 403
        helena_mock.send_unique.assert_not_called()

    async def test_unverified_org_gets_403(
        self, db_session, auth_as, make_user_session_factory, helena_mock
    ):
        org, portfolio = await _portfolio(
            db_session, verification_status=VerificationStatus.PENDING
        )
        authed = auth_as(_member(make_user_session_factory, org.id))
        resp = await authed.post(BASE, json=_body(portfolio.id))
        assert resp.status_code == 403
        helena_mock.send_unique.assert_not_called()

    async def test_org_admin_can_call_until_hourly_limit(
        self, db_session, auth_as, make_user_session_factory, helena_mock
    ):
        org, portfolio = await _portfolio(db_session)
        authed = auth_as(_member(make_user_session_factory, org.id))
        for _ in range(TEST_CALLS_PER_HOUR):
            resp = await authed.post(BASE, json=_body(portfolio.id))
            assert resp.status_code == 200
        limited = await authed.post(BASE, json=_body(portfolio.id))
        assert limited.status_code == 429
        sent = helena_mock.send_unique.call_args.args[0]
        assert sent["campaignId"] == "TEST"
