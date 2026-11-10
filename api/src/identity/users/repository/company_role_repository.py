"""Acceso a datos de los roles de empresa, sus permisos y sus asignaciones."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from identity.users.models.company_role_model import CompanyRoleModel
from identity.users.models.company_role_permission_model import (
    CompanyRolePermissionModel,
)
from identity.users.models.permission_model import PermissionModel
from identity.users.models.user_company_role_model import UserCompanyRoleModel


class CompanyRoleRepository(SoftDeleteRepositoryBase[CompanyRoleModel]):
    model_class = CompanyRoleModel

    async def list_by_organization(
        self, organization_id: uuid.UUID
    ) -> list[CompanyRoleModel]:
        result = await self.session.execute(
            select(CompanyRoleModel)
            .where(
                CompanyRoleModel.organization_id == organization_id,
                CompanyRoleModel.deleted_at.is_(None),
            )
            .order_by(CompanyRoleModel.name)
        )
        return list(result.scalars().all())

    async def get_by_name(
        self, organization_id: uuid.UUID, name: str
    ) -> CompanyRoleModel | None:
        result = await self.session.execute(
            select(CompanyRoleModel).where(
                CompanyRoleModel.organization_id == organization_id,
                CompanyRoleModel.name == name,
                CompanyRoleModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_permission_names(self, company_role_id: uuid.UUID) -> list[str]:
        result = await self.session.execute(
            select(PermissionModel.name)
            .join(
                CompanyRolePermissionModel,
                CompanyRolePermissionModel.permission_id == PermissionModel.id,
            )
            .where(
                CompanyRolePermissionModel.company_role_id == company_role_id,
                CompanyRolePermissionModel.deleted_at.is_(None),
            )
            .order_by(PermissionModel.name)
        )
        return list(result.scalars().all())

    async def replace_permissions(
        self, company_role_id: uuid.UUID, permission_ids: list[uuid.UUID]
    ) -> None:
        """Reemplaza el conjunto completo de permisos del rol. Borrado físico (no
        soft-delete) porque la fila puente no tiene valor histórico propio una vez
        reemplazada -- lo auditable es el rol y sus permisos vigentes, que ya
        quedan en la auditoría de cambios del Bloque A cuando exista."""
        await self.session.execute(
            delete(CompanyRolePermissionModel).where(
                CompanyRolePermissionModel.company_role_id == company_role_id
            )
        )
        if permission_ids:
            await self.add_many_isolated(
                [
                    CompanyRolePermissionModel(
                        company_role_id=company_role_id, permission_id=permission_id
                    )
                    for permission_id in permission_ids
                ]
            )

    async def count_active_assignments(self, company_role_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(UserCompanyRoleModel.id).where(
                UserCompanyRoleModel.company_role_id == company_role_id,
                UserCompanyRoleModel.deleted_at.is_(None),
            )
        )
        return len(result.all())

    async def get_assigned_user_ids(
        self, company_role_id: uuid.UUID
    ) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(UserCompanyRoleModel.user_id).where(
                UserCompanyRoleModel.company_role_id == company_role_id,
                UserCompanyRoleModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_assignment(
        self, user_id: uuid.UUID, company_role_id: uuid.UUID
    ) -> UserCompanyRoleModel | None:
        result = await self.session.execute(
            select(UserCompanyRoleModel).where(
                UserCompanyRoleModel.user_id == user_id,
                UserCompanyRoleModel.company_role_id == company_role_id,
                UserCompanyRoleModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def assign_user(
        self, user_id: uuid.UUID, company_role_id: uuid.UUID, organization_id: uuid.UUID
    ) -> UserCompanyRoleModel:
        existing = await self.get_assignment(user_id, company_role_id)
        if existing:
            return existing
        return await self.add(
            UserCompanyRoleModel(
                user_id=user_id,
                company_role_id=company_role_id,
                organization_id=organization_id,
            )
        )

    async def unassign_user(
        self, user_id: uuid.UUID, company_role_id: uuid.UUID
    ) -> bool:
        existing = await self.get_assignment(user_id, company_role_id)
        if not existing:
            return False
        await self.delete(existing)
        return True

    async def get_user_role_ids(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(UserCompanyRoleModel.company_role_id).where(
                UserCompanyRoleModel.user_id == user_id,
                UserCompanyRoleModel.organization_id == organization_id,
                UserCompanyRoleModel.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_effective_permission_names_for_orgs(
        self, user_id: uuid.UUID, organization_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, frozenset[str]]:
        """Permisos efectivos que los roles de empresa del usuario le otorgan en cada
        organización -- se mezclan con los del rol fijo (`get_base_permissions`) y los
        overrides por usuario en `UserService.get_user_session`. Una sola consulta
        para todas las organizaciones del usuario (evita N+1 en ese loop)."""
        if not organization_ids:
            return {}
        result = await self.session.execute(
            select(UserCompanyRoleModel.organization_id, PermissionModel.name)
            .join(
                CompanyRolePermissionModel,
                CompanyRolePermissionModel.company_role_id
                == UserCompanyRoleModel.company_role_id,
            )
            .join(
                PermissionModel,
                PermissionModel.id == CompanyRolePermissionModel.permission_id,
            )
            .join(
                CompanyRoleModel,
                CompanyRoleModel.id == UserCompanyRoleModel.company_role_id,
            )
            .where(
                UserCompanyRoleModel.user_id == user_id,
                UserCompanyRoleModel.organization_id.in_(organization_ids),
                UserCompanyRoleModel.deleted_at.is_(None),
                CompanyRolePermissionModel.deleted_at.is_(None),
                CompanyRoleModel.is_active.is_(True),
                CompanyRoleModel.deleted_at.is_(None),
                PermissionModel.is_active.is_(True),
            )
        )
        names_by_org: dict[uuid.UUID, set[str]] = {}
        for org_id, name in result.all():
            names_by_org.setdefault(org_id, set()).add(name)
        return {org_id: frozenset(names) for org_id, names in names_by_org.items()}

    async def _role_ids_for_organization(
        self, organization_id: uuid.UUID
    ) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(CompanyRoleModel.id).where(
                CompanyRoleModel.organization_id == organization_id
            )
        )
        return list(result.scalars().all())

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja en cascada de los roles de empresa, sus permisos y sus asignaciones,
        con el mismo `deleted_at` que la organización (mismo criterio que
        `OrganizationCascadeService`: `restore_by_organization` revierte solo lo que
        cayó en esta cascada, no lo que ya estaba dado de baja antes).
        `soft_delete_where` no sirve aquí: siempre actualiza `self.model_class`
        (`CompanyRoleModel`), y dos de las tres tablas de esta cascada son otro
        modelo."""
        role_ids = await self._role_ids_for_organization(organization_id)
        if role_ids:
            await self.session.execute(
                update(CompanyRolePermissionModel)
                .where(
                    CompanyRolePermissionModel.company_role_id.in_(role_ids),
                    CompanyRolePermissionModel.deleted_at.is_(None),
                )
                .values(**self._touch(deleted_at=deleted_at))
            )
        await self.session.execute(
            update(UserCompanyRoleModel)
            .where(
                UserCompanyRoleModel.organization_id == organization_id,
                UserCompanyRoleModel.deleted_at.is_(None),
            )
            .values(**self._touch(deleted_at=deleted_at))
        )
        await self.soft_delete_where(
            CompanyRoleModel.organization_id == organization_id,
            deleted_at=deleted_at,
        )

    async def restore_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        await self.restore_where(
            CompanyRoleModel.organization_id == organization_id,
            deleted_at=deleted_at,
        )
        role_ids = await self._role_ids_for_organization(organization_id)
        await self.session.execute(
            update(UserCompanyRoleModel)
            .where(
                UserCompanyRoleModel.organization_id == organization_id,
                UserCompanyRoleModel.deleted_at == deleted_at,
            )
            .values(**self._touch(deleted_at=None))
        )
        if role_ids:
            await self.session.execute(
                update(CompanyRolePermissionModel)
                .where(
                    CompanyRolePermissionModel.company_role_id.in_(role_ids),
                    CompanyRolePermissionModel.deleted_at == deleted_at,
                )
                .values(**self._touch(deleted_at=None))
            )
