import uuid

import pytest
from fastapi import HTTPException

from core.security.policies.security_policies import (
    check_portfolio_org_access,
    get_self_identity,
    has_permission,
    require_admin_or_org,
    require_global,
    require_global_admin,
    require_org_access,
    require_org_admin,
    require_org_or_global,
    require_permission,
    require_portfolio_access,
    require_self,
    require_verified_org,
)
from identity.organizations.enums.organization_enums import VerificationStatus
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_session_schema import OrgSessionEntry, UserSession


def _session(**overrides) -> UserSession:
    defaults = dict(
        user_id=uuid.uuid4(),
        full_name="Test User",
        email="test@example.com",
        role=UserRole.USER,
        scope=UserScope.SELF,
    )
    defaults.update(overrides)
    return UserSession(**defaults)


class _FakePortfolio:
    def __init__(self, organization_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.organization_id = organization_id


async def _granted(_user_id, _portfolio_id, _org_id) -> bool:
    return True


async def _not_granted(_user_id, _portfolio_id, _org_id) -> bool:
    return False


class TestRequireGlobal:
    def test_global_session_passes(self):
        require_global(_session(scope=UserScope.GLOBAL))

    def test_non_global_session_raises_403(self):
        with pytest.raises(HTTPException) as exc:
            require_global(_session(scope=UserScope.SELF))
        assert exc.value.status_code == 403


class TestRequireGlobalAdmin:
    def test_global_admin_passes(self):
        require_global_admin(_session(scope=UserScope.GLOBAL, role=UserRole.ADMIN))

    def test_global_non_admin_raises_403(self):
        with pytest.raises(HTTPException):
            require_global_admin(_session(scope=UserScope.GLOBAL, role=UserRole.USER))

    def test_non_global_admin_raises_403(self):
        with pytest.raises(HTTPException):
            require_global_admin(_session(scope=UserScope.SELF, role=UserRole.ADMIN))


class TestRequireOrgOrGlobal:
    def test_global_passes(self):
        require_org_or_global(_session(scope=UserScope.GLOBAL))

    def test_with_orgs_passes(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.USER, org_name="Org")},
        )
        require_org_or_global(session)

    def test_self_without_orgs_raises_403(self):
        with pytest.raises(HTTPException):
            require_org_or_global(_session(scope=UserScope.SELF))


class TestRequireOrgAdmin:
    def test_global_bypasses_org_membership(self):
        require_org_admin(_session(scope=UserScope.GLOBAL), str(uuid.uuid4()))

    def test_admin_of_org_passes(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.ADMIN, org_name="Org")},
        )
        require_org_admin(session, org_id)

    def test_non_member_of_org_raises_403(self):
        session = _session(scope=UserScope.ORGANIZATION, orgs={})
        with pytest.raises(HTTPException) as exc:
            require_org_admin(session, str(uuid.uuid4()))
        assert exc.value.status_code == 403

    def test_non_admin_member_raises_403(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.USER, org_name="Org")},
        )
        with pytest.raises(HTTPException):
            require_org_admin(session, org_id)


class TestRequirePermission:
    def test_global_bypasses_permission_check(self):
        require_permission(
            "any.perm", _session(scope=UserScope.GLOBAL), str(uuid.uuid4())
        )

    def test_org_member_with_permission_passes(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={
                org_id: OrgSessionEntry(
                    role=UserRole.USER,
                    org_name="Org",
                    permissions=frozenset({"orgs.users"}),
                )
            },
        )
        require_permission("orgs.users", session, org_id)

    def test_org_member_without_permission_raises_403(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.USER, org_name="Org")},
        )
        with pytest.raises(HTTPException):
            require_permission("orgs.users", session, org_id)

    def test_non_member_of_org_raises_403(self):
        session = _session(scope=UserScope.ORGANIZATION, orgs={})
        with pytest.raises(HTTPException):
            require_permission("orgs.users", session, str(uuid.uuid4()))


class TestHasPermission:
    def test_global_has_every_permission(self):
        assert (
            has_permission(
                "any.perm", _session(scope=UserScope.GLOBAL), str(uuid.uuid4())
            )
            is True
        )

    def test_org_member_with_permission(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={
                org_id: OrgSessionEntry(
                    role=UserRole.USER,
                    org_name="Org",
                    permissions=frozenset({"portfolio.clients"}),
                )
            },
        )
        assert has_permission("portfolio.clients", session, org_id) is True

    def test_org_member_without_permission(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={
                org_id: OrgSessionEntry(
                    role=UserRole.USER,
                    org_name="Org",
                    permissions=frozenset({"portfolio.communications"}),
                )
            },
        )
        assert has_permission("portfolio.clients", session, org_id) is False

    def test_permission_in_another_org_does_not_count(self):
        own_org, other_org = str(uuid.uuid4()), str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={
                own_org: OrgSessionEntry(
                    role=UserRole.USER,
                    org_name="Org",
                    permissions=frozenset({"portfolio.clients"}),
                )
            },
        )
        assert has_permission("portfolio.clients", session, other_org) is False


class TestRequireAdminOrOrg:
    def test_global_bypasses(self):
        require_admin_or_org(
            "orgs.users", _session(scope=UserScope.GLOBAL), str(uuid.uuid4())
        )

    def test_org_admin_bypasses_permission_check(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.ADMIN, org_name="Org")},
        )
        require_admin_or_org("orgs.users", session, org_id)

    def test_non_admin_with_permission_passes(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={
                org_id: OrgSessionEntry(
                    role=UserRole.USER,
                    org_name="Org",
                    permissions=frozenset({"orgs.users"}),
                )
            },
        )
        require_admin_or_org("orgs.users", session, org_id)

    def test_non_admin_without_permission_raises_403(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.USER, org_name="Org")},
        )
        with pytest.raises(HTTPException):
            require_admin_or_org("orgs.users", session, org_id)

    def test_non_member_of_org_raises_403(self):
        session = _session(scope=UserScope.ORGANIZATION, orgs={})
        with pytest.raises(HTTPException):
            require_admin_or_org("orgs.users", session, str(uuid.uuid4()))


class TestRequireOrgAccess:
    def test_global_bypasses(self):
        require_org_access(_session(scope=UserScope.GLOBAL), str(uuid.uuid4()))

    def test_member_of_org_passes(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.USER, org_name="Org")},
        )
        require_org_access(session, org_id)

    def test_non_member_raises_403(self):
        session = _session(scope=UserScope.ORGANIZATION, orgs={})
        with pytest.raises(HTTPException):
            require_org_access(session, str(uuid.uuid4()))


class TestRequireVerifiedOrg:
    def test_approved_org_passes(self):
        require_verified_org(_FakeOrgVerification(VerificationStatus.APPROVED))

    def test_pending_org_raises_403(self):
        with pytest.raises(HTTPException):
            require_verified_org(_FakeOrgVerification(VerificationStatus.PENDING))

    def test_none_org_raises_403(self):
        with pytest.raises(HTTPException):
            require_verified_org(None)


class _FakeOrgVerification:
    def __init__(self, status: VerificationStatus) -> None:
        self.verification_status = status


class TestRequireSelf:
    def test_self_scope_passes(self):
        require_self(_session(scope=UserScope.SELF))

    def test_non_self_scope_raises_403(self):
        with pytest.raises(HTTPException):
            require_self(_session(scope=UserScope.GLOBAL))


class TestGetSelfIdentity:
    def test_returns_document_tuple_when_complete(self):
        session = _session(document_type="CC", document_number_hash="hash123")
        assert get_self_identity(session) == ("CC", "hash123")

    def test_missing_document_raises_403(self):
        with pytest.raises(HTTPException):
            get_self_identity(_session(document_type=None, document_number_hash=None))


class TestCheckPortfolioOrgAccess:
    async def test_missing_portfolio_raises_404(self):
        with pytest.raises(HTTPException) as exc:
            await check_portfolio_org_access(
                _session(scope=UserScope.GLOBAL),
                None,
                "portfolio.view",
                check_access=_granted,
            )
        assert exc.value.status_code == 404

    async def test_global_session_bypasses_permission(self):
        org_id = uuid.uuid4()
        result = await check_portfolio_org_access(
            _session(scope=UserScope.GLOBAL),
            _FakePortfolio(org_id),
            "portfolio.view",
            check_access=_not_granted,
        )
        assert result == org_id

    async def test_org_member_without_permission_raises_403(self):
        org_id = uuid.uuid4()
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={str(org_id): OrgSessionEntry(role=UserRole.USER, org_name="Org")},
        )
        with pytest.raises(HTTPException):
            await check_portfolio_org_access(
                session,
                _FakePortfolio(org_id),
                "portfolio.view",
                check_access=_granted,
            )

    async def test_member_with_permission_but_no_grant_raises_403(self):
        org_id = uuid.uuid4()
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={
                str(org_id): OrgSessionEntry(
                    role=UserRole.USER,
                    org_name="Org",
                    permissions=frozenset({"portfolio.view"}),
                )
            },
        )
        with pytest.raises(HTTPException) as exc:
            await check_portfolio_org_access(
                session,
                _FakePortfolio(org_id),
                "portfolio.view",
                check_access=_not_granted,
            )
        assert exc.value.status_code == 403

    async def test_member_with_permission_and_grant_passes(self):
        org_id = uuid.uuid4()
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={
                str(org_id): OrgSessionEntry(
                    role=UserRole.USER,
                    org_name="Org",
                    permissions=frozenset({"portfolio.view"}),
                )
            },
        )
        result = await check_portfolio_org_access(
            session,
            _FakePortfolio(org_id),
            "portfolio.view",
            check_access=_granted,
        )
        assert result == org_id


class TestRequirePortfolioAccess:
    async def test_global_bypasses_check_callback(self):
        called = False

        async def _check(user_id, portfolio_id, org_id):
            nonlocal called
            called = True
            return False

        await require_portfolio_access(
            _session(scope=UserScope.GLOBAL), str(uuid.uuid4()), uuid.uuid4(), _check
        )
        assert called is False

    async def test_org_admin_bypasses_check_callback(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.ADMIN, org_name="Org")},
        )

        async def _check(user_id, portfolio_id, oid):
            raise AssertionError("no debería llamarse para un admin de org")

        await require_portfolio_access(session, org_id, uuid.uuid4(), _check)

    async def test_non_admin_denied_by_callback_raises_403(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.USER, org_name="Org")},
        )

        async def _check(user_id, portfolio_id, oid):
            return False

        with pytest.raises(HTTPException):
            await require_portfolio_access(session, org_id, uuid.uuid4(), _check)

    async def test_non_admin_allowed_by_callback_passes(self):
        org_id = str(uuid.uuid4())
        session = _session(
            scope=UserScope.ORGANIZATION,
            orgs={org_id: OrgSessionEntry(role=UserRole.USER, org_name="Org")},
        )

        async def _check(user_id, portfolio_id, oid):
            return True

        await require_portfolio_access(session, org_id, uuid.uuid4(), _check)

    async def test_non_member_of_org_raises_403(self):
        session = _session(scope=UserScope.ORGANIZATION, orgs={})

        async def _check(user_id, portfolio_id, oid):
            return True

        with pytest.raises(HTTPException):
            await require_portfolio_access(
                session, str(uuid.uuid4()), uuid.uuid4(), _check
            )
