"""Gestión de usuarios administrados: alta, roles y permisos delegados."""

from __future__ import annotations

import uuid
from typing import cast

from fastapi import HTTPException, status

from core.database.redis import redis_client
from core.security.services.password_hasher_service import PasswordHasherService
from identity.auth.enums.auth_enums import AuthProvider
from identity.auth.utils.auth_utils import normalize_email, require_value
from identity.organizations.models.organization_membership_model import (
    OrganizationMembershipModel,
)
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.users.enums.user_enums import (
    VALID_ROLE_SCOPE,
    PermissionEffect,
    UserRole,
    UserScope,
)
from identity.users.models.role_assignment_model import RoleAssignmentModel
from identity.users.models.user_model import UserModel
from identity.users.repository.permission_assignment_repository import (
    PermissionAssignmentRepository,
)
from identity.users.repository.role_assignment_repository import (
    RoleAssignmentRepository,
)
from identity.users.repository.user_repository import UserRepository
from identity.users.schemas.user_management_schemas import (
    ManagedUserCreate,
    ManagedUserResponse,
    PermissionCatalogEntry,
    PermissionEntry,
    PermissionListResponse,
)
from identity.users.schemas.user_session_schema import session_key

_GLOBAL_ROLES = {UserRole.ADMIN, UserRole.CUSTOMER_SERVICE}
_ORG_ROLES = {UserRole.ADMIN, UserRole.CUSTOMER_SERVICE, UserRole.USER}


class UserManagementService:
    def __init__(
        self,
        user_repo: UserRepository,
        role_assignment_repo: RoleAssignmentRepository,
        membership_repo: OrganizationMembershipRepository,
        permission_assignment_repo: PermissionAssignmentRepository,
        password_hasher: PasswordHasherService | None = None,
    ):
        self.user_repo = user_repo
        self.role_assignment_repo = role_assignment_repo
        self.membership_repo = membership_repo
        self.permission_assignment_repo = permission_assignment_repo
        self.password_hasher = password_hasher or PasswordHasherService()

    async def _create_base_user(self, data: ManagedUserCreate) -> UserModel:
        email = normalize_email(data.email)
        phone = require_value(
            data.phone_number, "El número de teléfono es obligatorio."
        )
        firstname = require_value(data.firstname, "El nombre es obligatorio.")
        lastname = require_value(data.lastname, "El apellido es obligatorio.")
        password = require_value(data.password, "La contraseña es obligatoria.")

        if await self.user_repo.get_by_email(email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El correo ya está registrado.",
            )
        if await self.user_repo.get_by_phone_number(phone):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El teléfono ya está registrado.",
            )

        user = UserModel(
            firstname=firstname,
            lastname=lastname,
            email=email,
            hashed_password=self.password_hasher.hash_password(password),
            phone_number=phone,
            auth_provider=AuthProvider.SELF,
        )
        return await self.user_repo.add(user)

    async def create_global_user(self, data: ManagedUserCreate) -> ManagedUserResponse:
        if data.role not in _GLOBAL_ROLES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Rol inválido para usuarios globales. Permitidos: "
                    f"{[r.value for r in _GLOBAL_ROLES]}"
                ),
            )
        if (data.role, UserScope.GLOBAL) not in VALID_ROLE_SCOPE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Combinación rol-scope inválida.",
            )

        user = await self._create_base_user(data)
        await self.role_assignment_repo.add(
            RoleAssignmentModel(user_id=user.id, role=data.role, scope=UserScope.GLOBAL)
        )
        return ManagedUserResponse(
            id=user.id,
            full_name=user.full_name,
            email=cast(str, user.email),
            phone_number=cast(str, user.phone_number),
            role=data.role.value,
            scope=UserScope.GLOBAL.value,
        )

    async def create_org_member(
        self, actor_id: uuid.UUID, org_id: uuid.UUID, data: ManagedUserCreate
    ) -> ManagedUserResponse:
        if data.role not in _ORG_ROLES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Rol inválido para miembros de organización. Permitidos: "
                    f"{[r.value for r in _ORG_ROLES]}"
                ),
            )
        if (data.role, UserScope.ORGANIZATION) not in VALID_ROLE_SCOPE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Combinación rol-scope inválida.",
            )

        user = await self._create_base_user(data)
        await self.role_assignment_repo.add(
            RoleAssignmentModel(
                user_id=user.id,
                role=data.role,
                scope=UserScope.ORGANIZATION,
                organization_id=org_id,
            )
        )
        await self.membership_repo.add(
            OrganizationMembershipModel(
                user_id=user.id,
                organization_id=org_id,
                created_by=actor_id,
            )
        )
        return ManagedUserResponse(
            id=user.id,
            full_name=user.full_name,
            email=cast(str, user.email),
            phone_number=cast(str, user.phone_number),
            role=data.role.value,
            scope=UserScope.ORGANIZATION.value,
        )

    async def _require_member(self, user_id: uuid.UUID, org_id: uuid.UUID) -> None:
        """Los permisos por usuario solo se otorgan a miembros de la organización que
        no sean personal GLOBAL (mismo criterio que
        `UserService.assert_can_manage_user`); si no, 404 (no se confirma que el
        usuario exista en otro lado)."""
        not_found = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Miembro no encontrado."
        )
        if await self.role_assignment_repo.get_global_user_ids([user_id]):
            raise not_found
        memberships = await self.membership_repo.get_by_user_id(user_id)
        if not any(m.organization_id == org_id for m in memberships):
            raise not_found

    async def list_permissions(
        self, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> PermissionListResponse:
        await self._require_member(user_id, org_id)
        overrides = await self.permission_assignment_repo.get_overrides_for_user_org(
            user_id, org_id
        )
        return PermissionListResponse(
            permissions=[
                PermissionEntry(name=name, effect=effect.value)
                for name, effect in overrides
            ]
        )

    async def assign_permission(
        self,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        permission_name: str,
        effect: PermissionEffect,
    ) -> PermissionEntry:
        await self._require_member(user_id, org_id)
        perm = await self.permission_assignment_repo.get_permission_by_name(
            permission_name
        )
        if perm is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permiso '{permission_name}' no encontrado.",
            )
        await self.permission_assignment_repo.upsert_for_org(
            user_id=user_id,
            permission_id=perm.id,
            organization_id=org_id,
            effect=effect,
        )
        # La sesión cacheada lleva los permisos: sin esto el cambio no se ve
        # hasta que expire.
        await redis_client.delete(session_key(user_id))
        return PermissionEntry(name=permission_name, effect=effect.value)

    async def get_permissions_catalog(self) -> list[PermissionCatalogEntry]:
        permissions = await self.permission_assignment_repo.get_all_active_permissions()
        return [
            PermissionCatalogEntry(
                name=p.name, label=p.label, description=p.description
            )
            for p in permissions
        ]

    async def remove_permission(
        self, user_id: uuid.UUID, org_id: uuid.UUID, permission_name: str
    ) -> None:
        await self._require_member(user_id, org_id)
        perm = await self.permission_assignment_repo.get_permission_by_name(
            permission_name
        )
        if perm is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permiso '{permission_name}' no encontrado.",
            )
        deleted = await self.permission_assignment_repo.delete_for_org(
            user_id=user_id,
            permission_id=perm.id,
            organization_id=org_id,
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Asignación de permiso no encontrada.",
            )
        await redis_client.delete(session_key(user_id))
