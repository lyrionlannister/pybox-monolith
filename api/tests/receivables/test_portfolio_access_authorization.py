"""Autorización cruzada entre organizaciones en portafolios y accesos por usuario.

Riesgos cubiertos:
  * un admin de la organización A no puede revocar/conceder accesos sobre un portafolio
    de la organización B (el `org_id` del path se valida, el `portfolio_id` también);
  * los accesos solo se conceden a miembros de la organización;
  * quien no pertenece a la organización dueña recibe 404 -- igual que para un ID que no
    existe -- y no 403, que confirmaría que el portafolio existe en otro tenant;
  * crear un portafolio por CSV exige `portfolio.upload_new`, y agregar datos exige
    `portfolio.upload_update` Y acceso al portafolio concreto.
"""

import uuid

import pytest
from fastapi import HTTPException

from core.security.constants.permissions import (
    ORG_USERS,
    PORTFOLIO_CLIENTS,
    PORTFOLIO_UPLOAD_NEW,
    PORTFOLIO_UPLOAD_UPDATE,
)
from core.security.policies.security_policies import check_portfolio_org_access
from identity.organizations.enums.organization_enums import VerificationStatus
from identity.organizations.models.organization_membership_model import (
    OrganizationMembershipModel,
)
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.models.role_assignment_model import RoleAssignmentModel
from identity.users.schemas.user_session_schema import OrgSessionEntry
from receivables.portfolios.models.portfolio_user_access_model import (
    PortfolioUserAccessModel,
)
from receivables.portfolios.repository.portfolio_user_access_repository import (
    PortfolioUserAccessRepository,
)
from tests.factories import get_user_by_email, register_payload
from tests.receivables.conftest import (
    add_organization,
    build_portfolio,
    build_portfolio_csv,
    portfolio_csv_row,
)

AUTH_BASE = "/api/v1/auth"
PORTFOLIOS = "/api/v1/portfolios"
ORGS = "/api/v1/organizations"


async def _new_user(client, db_session) -> uuid.UUID:
    payload = register_payload()
    resp = await client.post(f"{AUTH_BASE}/register/user", json=payload)
    assert resp.status_code == 201
    return (await get_user_by_email(db_session, payload["email"])).id


async def _add_member(
    db_session, user_id, org_id, role: UserRole = UserRole.USER
) -> None:
    db_session.add_all(
        [
            OrganizationMembershipModel(
                user_id=user_id, organization_id=org_id, created_by=user_id
            ),
            RoleAssignmentModel(
                user_id=user_id,
                role=role,
                scope=UserScope.ORGANIZATION,
                organization_id=org_id,
            ),
        ]
    )
    await db_session.flush()


def _session(
    make_user_session_factory,
    user_id,
    org_id,
    role: UserRole,
    permissions: frozenset[str] = frozenset(),
):
    return make_user_session_factory(
        user_id=user_id,
        role=role,
        scope=UserScope.ORGANIZATION,
        orgs={
            str(org_id): OrgSessionEntry(
                role=role,
                org_name="Org",
                permissions=permissions,
                verification_status=VerificationStatus.APPROVED,
            )
        },
    )


@pytest.fixture
async def org_a(db_session):
    return await add_organization(db_session)


@pytest.fixture
async def org_b(db_session):
    return await add_organization(db_session)


@pytest.fixture
async def portfolio_a(db_session, org_a):
    portfolio = build_portfolio(org_a.id)
    db_session.add(portfolio)
    await db_session.flush()
    return portfolio


@pytest.fixture
async def portfolio_b(db_session, org_b):
    portfolio = build_portfolio(org_b.id)
    db_session.add(portfolio)
    await db_session.flush()
    return portfolio


@pytest.fixture
async def admin_a_id(client, db_session, org_a):
    user_id = await _new_user(client, db_session)
    await _add_member(db_session, user_id, org_a.id, UserRole.ADMIN)
    return user_id


@pytest.fixture
async def member_a_id(client, db_session, org_a):
    user_id = await _new_user(client, db_session)
    await _add_member(db_session, user_id, org_a.id, UserRole.USER)
    return user_id


@pytest.fixture
async def member_b_id(client, db_session, org_b):
    user_id = await _new_user(client, db_session)
    await _add_member(db_session, user_id, org_b.id, UserRole.USER)
    return user_id


async def _deny_all(_user_id, _portfolio_id, _org_id) -> bool:
    return False


class TestMemberPortfolioAccess:
    async def test_admin_cannot_revoke_access_on_another_organizations_portfolio(
        self,
        db_session,
        auth_as,
        make_user_session_factory,
        org_a,
        admin_a_id,
        member_b_id,
        portfolio_b,
    ):
        db_session.add(
            PortfolioUserAccessModel(
                user_id=member_b_id,
                portfolio_id=portfolio_b.id,
                organization_id=portfolio_b.organization_id,
                granted_by=member_b_id,
            )
        )
        await db_session.flush()
        session = _session(
            make_user_session_factory, admin_a_id, org_a.id, UserRole.ADMIN
        )

        resp = await auth_as(session).delete(
            f"{ORGS}/{org_a.id}/members/{member_b_id}/portfolios/{portfolio_b.id}"
        )

        assert resp.status_code == 404
        db_session.expunge_all()
        assert await PortfolioUserAccessRepository(db_session).check_active_access(
            member_b_id, portfolio_b.id, portfolio_b.organization_id
        )

    async def test_admin_cannot_grant_access_on_another_organizations_portfolio(
        self,
        auth_as,
        make_user_session_factory,
        org_a,
        admin_a_id,
        member_a_id,
        portfolio_b,
    ):
        session = _session(
            make_user_session_factory, admin_a_id, org_a.id, UserRole.ADMIN
        )

        resp = await auth_as(session).put(
            f"{ORGS}/{org_a.id}/members/{member_a_id}/portfolios/{portfolio_b.id}"
        )

        assert resp.status_code == 404

    async def test_cannot_grant_access_to_a_non_member(
        self,
        auth_as,
        make_user_session_factory,
        org_a,
        admin_a_id,
        member_b_id,
        portfolio_a,
    ):
        session = _session(
            make_user_session_factory, admin_a_id, org_a.id, UserRole.ADMIN
        )

        resp = await auth_as(session).put(
            f"{ORGS}/{org_a.id}/members/{member_b_id}/portfolios/{portfolio_a.id}"
        )

        assert resp.status_code == 404

    async def test_grant_and_revoke_work_within_the_same_organization(
        self,
        db_session,
        auth_as,
        make_user_session_factory,
        org_a,
        admin_a_id,
        member_a_id,
        portfolio_a,
    ):
        client = auth_as(
            _session(make_user_session_factory, admin_a_id, org_a.id, UserRole.ADMIN)
        )
        url = f"{ORGS}/{org_a.id}/members/{member_a_id}/portfolios/{portfolio_a.id}"
        repo = PortfolioUserAccessRepository(db_session)

        assert (await client.put(url)).status_code == 200
        db_session.expunge_all()
        assert await repo.check_active_access(member_a_id, portfolio_a.id, org_a.id)

        assert (await client.delete(url)).status_code == 204
        db_session.expunge_all()
        assert not await repo.check_active_access(member_a_id, portfolio_a.id, org_a.id)

    async def test_cannot_list_portfolio_access_status_of_a_non_member(
        self, auth_as, make_user_session_factory, org_a, admin_a_id, member_b_id
    ):
        session = _session(
            make_user_session_factory, admin_a_id, org_a.id, UserRole.ADMIN
        )

        resp = await auth_as(session).get(
            f"{ORGS}/{org_a.id}/members/{member_b_id}/portfolios"
        )

        assert resp.status_code == 404

    async def test_replace_access_rejects_a_non_member(
        self,
        auth_as,
        make_user_session_factory,
        org_a,
        admin_a_id,
        member_b_id,
        portfolio_a,
    ):
        session = _session(
            make_user_session_factory, admin_a_id, org_a.id, UserRole.ADMIN
        )

        resp = await auth_as(session).put(
            f"{PORTFOLIOS}/{portfolio_a.id}/access",
            json={"userIds": [str(member_b_id)]},
        )

        assert resp.status_code == 404


class TestForeignPortfolioIsNotFound:
    """Un miembro de la organización A no distingue "existe en B" de "no existe"."""

    @pytest.mark.parametrize(
        ("method", "suffix"),
        [
            ("get", ""),
            ("patch", ""),
            ("delete", ""),
            ("get", "/stats"),
            ("get", "/access"),
            ("get", "/daily-counter-config"),
        ],
    )
    async def test_foreign_portfolio_returns_404(
        self,
        auth_as,
        make_user_session_factory,
        org_a,
        admin_a_id,
        portfolio_b,
        method,
        suffix,
    ):
        client = auth_as(
            _session(make_user_session_factory, admin_a_id, org_a.id, UserRole.ADMIN)
        )
        kwargs = {"json": {}} if method == "patch" else {}

        foreign = await getattr(client, method)(
            f"{PORTFOLIOS}/{portfolio_b.id}{suffix}", **kwargs
        )
        missing = await getattr(client, method)(
            f"{PORTFOLIOS}/{uuid.uuid4()}{suffix}", **kwargs
        )

        assert foreign.status_code == 404
        assert foreign.status_code == missing.status_code

    async def test_check_portfolio_org_access_hides_foreign_portfolios(
        self, make_user_session_factory, org_a, admin_a_id, portfolio_b
    ):
        session = _session(
            make_user_session_factory,
            admin_a_id,
            org_a.id,
            UserRole.ADMIN,
            frozenset({PORTFOLIO_CLIENTS}),
        )

        with pytest.raises(HTTPException) as exc:
            await check_portfolio_org_access(
                session, portfolio_b, PORTFOLIO_CLIENTS, check_access=_deny_all
            )

        assert exc.value.status_code == 404

    async def test_check_portfolio_org_access_still_denies_members_without_permission(
        self, make_user_session_factory, org_a, member_a_id, portfolio_a
    ):
        session = _session(
            make_user_session_factory, member_a_id, org_a.id, UserRole.USER, frozenset()
        )

        with pytest.raises(HTTPException) as exc:
            await check_portfolio_org_access(
                session, portfolio_a, PORTFOLIO_CLIENTS, check_access=_deny_all
            )

        assert exc.value.status_code == 403


class TestCsvUploadAuthorization:
    def _file(self):
        return {
            "file": (
                "cartera.csv",
                build_portfolio_csv([portfolio_csv_row()]),
                "text/csv",
            )
        }

    async def test_creating_a_portfolio_requires_upload_new_permission(
        self, auth_as, make_user_session_factory, org_a, member_a_id
    ):
        session = _session(
            make_user_session_factory,
            member_a_id,
            org_a.id,
            UserRole.USER,
            frozenset({ORG_USERS}),
        )

        resp = await auth_as(session).post(
            f"{PORTFOLIOS}/upload-csv?organizationId={org_a.id}&portfolioName=Nueva",
            files=self._file(),
        )

        assert resp.status_code == 403

    async def test_creating_a_portfolio_in_another_organization_is_denied(
        self, auth_as, make_user_session_factory, org_a, org_b, admin_a_id
    ):
        session = _session(
            make_user_session_factory,
            admin_a_id,
            org_a.id,
            UserRole.ADMIN,
            frozenset({PORTFOLIO_UPLOAD_NEW}),
        )

        resp = await auth_as(session).post(
            f"{PORTFOLIOS}/upload-csv?organizationId={org_b.id}&portfolioName=Nueva",
            files=self._file(),
        )

        assert resp.status_code == 403

    async def test_append_requires_access_to_that_specific_portfolio(
        self, auth_as, make_user_session_factory, org_a, member_a_id, portfolio_a
    ):
        # Tiene el permiso, pero no acceso a ESTE portafolio.
        session = _session(
            make_user_session_factory,
            member_a_id,
            org_a.id,
            UserRole.USER,
            frozenset({PORTFOLIO_UPLOAD_UPDATE}),
        )

        resp = await auth_as(session).post(
            f"{PORTFOLIOS}/upload-csv/append?portfolioId={portfolio_a.id}",
            files=self._file(),
        )

        assert resp.status_code == 403

    async def test_append_to_a_foreign_portfolio_is_not_found(
        self, auth_as, make_user_session_factory, org_a, admin_a_id, portfolio_b
    ):
        session = _session(
            make_user_session_factory,
            admin_a_id,
            org_a.id,
            UserRole.ADMIN,
            frozenset({PORTFOLIO_UPLOAD_UPDATE}),
        )

        resp = await auth_as(session).post(
            f"{PORTFOLIOS}/upload-csv/append?portfolioId={portfolio_b.id}",
            files=self._file(),
        )

        assert resp.status_code == 404
