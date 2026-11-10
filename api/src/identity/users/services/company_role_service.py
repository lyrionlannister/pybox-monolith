"""Roles de empresa: nombre + conjunto de permisos del catálogo, definidos y
asignados por cada organización sobre el motor de permisos existente."""

import uuid

from fastapi import HTTPException, status

from core.database.redis import redis_client
from core.security.constants.permissions import ORG_USERS
from core.security.policies.security_policies import (
    require_admin_or_org,
    require_org_access,
)
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.users.models.company_role_model import CompanyRoleModel
from identity.users.repository.company_role_repository import CompanyRoleRepository
from identity.users.repository.permission_assignment_repository import (
    PermissionAssignmentRepository,
)
from identity.users.schemas.company_role_schemas import (
    CompanyRoleCreate,
    CompanyRoleResponse,
    CompanyRoleUpdate,
)
from identity.users.schemas.user_session_schema import UserSession, session_key

# Plantilla sugerida al crear la empresa (párr. 63 del plan): un punto de partida
# editable y eliminable, no dos roles fijos para todas las empresas.
_JUNIOR_EXCLUDED_PERMISSIONS = {ORG_USERS, "org.billing", "org.payment_methods"}


class CompanyRoleService:
    def __init__(
        self,
        company_role_repo: CompanyRoleRepository,
        permission_assignment_repo: PermissionAssignmentRepository,
        membership_repo: OrganizationMembershipRepository,
    ):
        self.company_role_repo = company_role_repo
        self.permission_assignment_repo = permission_assignment_repo
        self.membership_repo = membership_repo

    async def _resolve_permission_ids(
        self, permission_names: list[str]
    ) -> list[uuid.UUID]:
        if not permission_names:
            return []
        catalog = await self.permission_assignment_repo.get_all_active_permissions()
        by_name = {p.name: p.id for p in catalog}
        missing = [name for name in permission_names if name not in by_name]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Permiso(s) fuera del catálogo: {', '.join(missing)}",
            )
        # dict.fromkeys en vez de set(): conserva el orden de llegada sin duplicar.
        return [by_name[name] for name in dict.fromkeys(permission_names)]

    async def _to_response(self, role: CompanyRoleModel) -> CompanyRoleResponse:
        permission_names = await self.company_role_repo.get_permission_names(role.id)
        return CompanyRoleResponse(
            id=role.id,
            name=role.name,
            description=role.description,
            is_active=role.is_active,
            permission_names=permission_names,
        )

    async def _require_role(
        self, org_id: uuid.UUID, role_id: uuid.UUID
    ) -> CompanyRoleModel:
        role = await self.company_role_repo.get_by_id(role_id)
        if role is None or role.organization_id != org_id:
            # 404 (no 403): no confirmar que un rol de otra organización existe.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Rol no encontrado")
        return role

    async def list_roles(
        self, session: UserSession, org_id: uuid.UUID
    ) -> list[CompanyRoleResponse]:
        require_org_access(session, str(org_id))
        roles = await self.company_role_repo.list_by_organization(org_id)
        return [await self._to_response(r) for r in roles]

    async def create_role(
        self, session: UserSession, org_id: uuid.UUID, data: CompanyRoleCreate
    ) -> CompanyRoleResponse:
        require_admin_or_org(ORG_USERS, session, str(org_id))
        if await self.company_role_repo.get_by_name(org_id, data.name):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Ya existe un rol con ese nombre"
            )
        permission_ids = await self._resolve_permission_ids(data.permission_names)
        role = await self.company_role_repo.add(
            CompanyRoleModel(
                organization_id=org_id,
                name=data.name,
                description=data.description,
            )
        )
        await self.company_role_repo.replace_permissions(role.id, permission_ids)
        return await self._to_response(role)

    async def update_role(
        self,
        session: UserSession,
        org_id: uuid.UUID,
        role_id: uuid.UUID,
        data: CompanyRoleUpdate,
    ) -> CompanyRoleResponse:
        require_admin_or_org(ORG_USERS, session, str(org_id))
        role = await self._require_role(org_id, role_id)
        if data.name is not None and data.name != role.name:
            duplicate = await self.company_role_repo.get_by_name(org_id, data.name)
            if duplicate and duplicate.id != role.id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "Ya existe un rol con ese nombre"
                )
            role.name = data.name
        if data.description is not None:
            role.description = data.description
        if data.is_active is not None:
            role.is_active = data.is_active
        await self.company_role_repo.update(role)
        if data.permission_names is not None:
            permission_ids = await self._resolve_permission_ids(data.permission_names)
            await self.company_role_repo.replace_permissions(role.id, permission_ids)
            await self._invalidate_sessions(role.id)
        return await self._to_response(role)

    async def _invalidate_sessions(self, role_id: uuid.UUID) -> None:
        """La sesión cacheada lleva los permisos efectivos: sin esto, un cambio en
        los permisos del rol o en sus asignaciones no se ve hasta que expire."""
        user_ids = await self.company_role_repo.get_assigned_user_ids(role_id)
        for user_id in user_ids:
            await redis_client.delete(session_key(user_id))

    async def delete_role(
        self, session: UserSession, org_id: uuid.UUID, role_id: uuid.UUID
    ) -> None:
        require_admin_or_org(ORG_USERS, session, str(org_id))
        role = await self._require_role(org_id, role_id)
        if await self.company_role_repo.count_active_assignments(role.id) > 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Reasigna a los usuarios de este rol antes de borrarlo",
            )
        await self.company_role_repo.delete(role)

    async def _require_org_member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
        memberships = await self.membership_repo.get_by_user_id(user_id)
        if not any(m.organization_id == org_id for m in memberships):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Miembro no encontrado")

    async def assign_user(
        self,
        session: UserSession,
        org_id: uuid.UUID,
        role_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        require_admin_or_org(ORG_USERS, session, str(org_id))
        await self._require_role(org_id, role_id)
        await self._require_org_member(org_id, user_id)
        await self.company_role_repo.assign_user(user_id, role_id, org_id)
        await redis_client.delete(session_key(user_id))

    async def unassign_user(
        self,
        session: UserSession,
        org_id: uuid.UUID,
        role_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        require_admin_or_org(ORG_USERS, session, str(org_id))
        await self._require_role(org_id, role_id)
        removed = await self.company_role_repo.unassign_user(user_id, role_id)
        if not removed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Asignación no encontrada")
        await redis_client.delete(session_key(user_id))

    async def list_assigned_user_ids(
        self, session: UserSession, org_id: uuid.UUID, role_id: uuid.UUID
    ) -> list[uuid.UUID]:
        require_org_access(session, str(org_id))
        await self._require_role(org_id, role_id)
        return await self.company_role_repo.get_assigned_user_ids(role_id)

    async def seed_example_roles(self, org_id: uuid.UUID) -> None:
        """Dos roles de ejemplo precargados al crear la empresa (párr. 63):
        editables y eliminables, no fijos para toda la plataforma."""
        catalog = await self.permission_assignment_repo.get_all_active_permissions()
        all_names = [p.name for p in catalog]
        junior_names = [
            name for name in all_names if name not in _JUNIOR_EXCLUDED_PERMISSIONS
        ]

        general = await self.company_role_repo.add(
            CompanyRoleModel(
                organization_id=org_id,
                name="Administrador General",
                description="Todos los permisos de la empresa.",
            )
        )
        await self.company_role_repo.replace_permissions(
            general.id, [p.id for p in catalog]
        )

        junior = await self.company_role_repo.add(
            CompanyRoleModel(
                organization_id=org_id,
                name="Administrador Junior",
                description=(
                    "Subconjunto operativo: sin gestión de usuarios, facturación "
                    "ni métodos de pago."
                ),
            )
        )
        junior_ids = [p.id for p in catalog if p.name in junior_names]
        await self.company_role_repo.replace_permissions(junior.id, junior_ids)
