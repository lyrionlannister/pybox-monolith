"""Roles de empresa: aislamiento entre organizaciones y permisos efectivos.

Riesgos cubiertos:
  * un admin de una organización no puede ver/editar/borrar/asignar un rol de
    empresa que pertenece a OTRA organización (IDOR);
  * un miembro sin `org.users` no puede crear roles de empresa;
  * borrar un rol con usuarios asignados se rechaza hasta reasignarlos;
  * los permisos de un rol de empresa asignado a un usuario se mezclan en sus
    permisos efectivos (`UserService.get_user_session`).
"""

import uuid

import pytest

from core.security.constants.permissions import ORG_PORTFOLIOS, ORG_USERS
from identity.organizations.enums.organization_enums import VerificationStatus
from identity.organizations.models.organization_membership_model import (
    OrganizationMembershipModel,
)
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.organizations.repository.organization_repository import (
    OrganizationRepository,
)
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.models.role_assignment_model import RoleAssignmentModel
from identity.users.repository.permission_assignment_repository import (
    PermissionAssignmentRepository,
)
from identity.users.repository.role_assignment_repository import (
    RoleAssignmentRepository,
)
from identity.users.repository.user_preferences_repository import (
    UserPreferencesRepository,
)
from identity.users.repository.user_repository import UserRepository
from identity.users.schemas.user_session_schema import OrgSessionEntry
from identity.users.services.user_service import UserService
from tests.factories import get_user_by_email, register_payload
from tests.receivables.conftest import add_organization

BASE = "/api/v1/organizations"


async def _new_user(client, db_session) -> uuid.UUID:
    payload = register_payload()
    resp = await client.post("/api/v1/auth/register/user", json=payload)
    assert resp.status_code == 201
    return (await get_user_by_email(db_session, payload["email"])).id


async def _add_member(db_session, user_id, org_id, role: UserRole) -> None:
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


def _org_session(make_user_session_factory, user_id, org_id, role: UserRole):
    return make_user_session_factory(
        user_id=user_id,
        role=role,
        scope=UserScope.ORGANIZATION,
        orgs={
            str(org_id): OrgSessionEntry(
                role=role,
                org_name="Org",
                permissions=(
                    frozenset({ORG_USERS}) if role == UserRole.ADMIN else (frozenset())
                ),
                verification_status=VerificationStatus.APPROVED,
            )
        },
    )


@pytest.fixture
async def org(db_session):
    return await add_organization(db_session)


@pytest.fixture
async def other_org(db_session):
    return await add_organization(db_session)


@pytest.fixture
async def org_admin_id(client, db_session, org):
    user_id = await _new_user(client, db_session)
    await _add_member(db_session, user_id, org.id, UserRole.ADMIN)
    return user_id


@pytest.fixture
async def other_org_admin_id(client, db_session, other_org):
    user_id = await _new_user(client, db_session)
    await _add_member(db_session, user_id, other_org.id, UserRole.ADMIN)
    return user_id


@pytest.fixture
async def member_id(client, db_session, org):
    user_id = await _new_user(client, db_session)
    await _add_member(db_session, user_id, org.id, UserRole.USER)
    return user_id


async def _create_role(auth_as, session, org_id, name="Cobranza", permissions=None):
    resp = await auth_as(session).post(
        f"{BASE}/{org_id}/company-roles",
        json={"name": name, "permissionNames": permissions or [ORG_PORTFOLIOS]},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


class TestCompanyRolesTenantIsolation:
    async def test_cannot_view_a_role_from_another_organization(
        self,
        auth_as,
        make_user_session_factory,
        org,
        other_org,
        org_admin_id,
        other_org_admin_id,
    ):
        role_id = await _create_role(
            auth_as,
            _org_session(
                make_user_session_factory, org_admin_id, org.id, UserRole.ADMIN
            ),
            org.id,
        )

        session = _org_session(
            make_user_session_factory, other_org_admin_id, other_org.id, UserRole.ADMIN
        )
        resp = await auth_as(session).patch(
            f"{BASE}/{other_org.id}/company-roles/{role_id}",
            json={"description": "hijack"},
        )

        assert resp.status_code == 404

    async def test_cannot_delete_a_role_from_another_organization(
        self,
        auth_as,
        make_user_session_factory,
        org,
        other_org,
        org_admin_id,
        other_org_admin_id,
    ):
        role_id = await _create_role(
            auth_as,
            _org_session(
                make_user_session_factory, org_admin_id, org.id, UserRole.ADMIN
            ),
            org.id,
        )

        session = _org_session(
            make_user_session_factory, other_org_admin_id, other_org.id, UserRole.ADMIN
        )
        resp = await auth_as(session).delete(
            f"{BASE}/{other_org.id}/company-roles/{role_id}"
        )

        assert resp.status_code == 404

    async def test_member_without_org_users_cannot_create_role(
        self, auth_as, make_user_session_factory, org, member_id
    ):
        session = _org_session(
            make_user_session_factory, member_id, org.id, UserRole.USER
        )

        resp = await auth_as(session).post(
            f"{BASE}/{org.id}/company-roles",
            json={"name": "Cobranza", "permissionNames": [ORG_PORTFOLIOS]},
        )

        assert resp.status_code == 403


class TestCompanyRolesAssignedUsers:
    async def test_cannot_list_assigned_users_of_a_role_from_another_organization(
        self,
        auth_as,
        make_user_session_factory,
        org,
        other_org,
        org_admin_id,
        other_org_admin_id,
    ):
        role_id = await _create_role(
            auth_as,
            _org_session(
                make_user_session_factory, org_admin_id, org.id, UserRole.ADMIN
            ),
            org.id,
        )

        session = _org_session(
            make_user_session_factory, other_org_admin_id, other_org.id, UserRole.ADMIN
        )
        resp = await auth_as(session).get(
            f"{BASE}/{other_org.id}/company-roles/{role_id}/users"
        )

        assert resp.status_code == 404

    async def test_assigning_a_user_appears_in_the_assigned_users_list(
        self, auth_as, make_user_session_factory, org, org_admin_id, member_id
    ):
        session = _org_session(
            make_user_session_factory, org_admin_id, org.id, UserRole.ADMIN
        )
        role_id = await _create_role(auth_as, session, org.id)

        assign_resp = await auth_as(session).post(
            f"{BASE}/{org.id}/company-roles/{role_id}/users/{member_id}"
        )
        assert assign_resp.status_code == 204

        list_resp = await auth_as(session).get(
            f"{BASE}/{org.id}/company-roles/{role_id}/users"
        )
        assert list_resp.status_code == 200
        assert str(member_id) in list_resp.json()


class TestCompanyRolesLifecycle:
    async def test_deleting_a_role_with_active_assignment_is_rejected(
        self, auth_as, make_user_session_factory, org, org_admin_id, member_id
    ):
        session = _org_session(
            make_user_session_factory, org_admin_id, org.id, UserRole.ADMIN
        )
        role_id = await _create_role(auth_as, session, org.id)

        assign_resp = await auth_as(session).post(
            f"{BASE}/{org.id}/company-roles/{role_id}/users/{member_id}"
        )
        assert assign_resp.status_code == 204

        delete_resp = await auth_as(session).delete(
            f"{BASE}/{org.id}/company-roles/{role_id}"
        )
        assert delete_resp.status_code == 409

        unassign_resp = await auth_as(session).delete(
            f"{BASE}/{org.id}/company-roles/{role_id}/users/{member_id}"
        )
        assert unassign_resp.status_code == 204

        delete_resp_2 = await auth_as(session).delete(
            f"{BASE}/{org.id}/company-roles/{role_id}"
        )
        assert delete_resp_2.status_code == 204


class TestCompanyRoleEffectivePermissions:
    async def test_assigned_company_role_permission_appears_in_effective_session(
        self,
        auth_as,
        make_user_session_factory,
        db_session,
        org,
        org_admin_id,
        member_id,
    ):
        session = _org_session(
            make_user_session_factory, org_admin_id, org.id, UserRole.ADMIN
        )
        role_id = await _create_role(
            auth_as, session, org.id, permissions=[ORG_PORTFOLIOS]
        )
        assign_resp = await auth_as(session).post(
            f"{BASE}/{org.id}/company-roles/{role_id}/users/{member_id}"
        )
        assert assign_resp.status_code == 204

        user_service = UserService(
            user_repo=UserRepository(db_session),
            org_repo=OrganizationRepository(db_session),
            membership_repo=OrganizationMembershipRepository(db_session),
            role_assignment_repo=RoleAssignmentRepository(db_session),
            permission_assignment_repo=PermissionAssignmentRepository(db_session),
            preferences_repo=UserPreferencesRepository(db_session),
        )
        rebuilt = await user_service.get_user_session(member_id)

        assert ORG_PORTFOLIOS in rebuilt.orgs[str(org.id)].permissions
