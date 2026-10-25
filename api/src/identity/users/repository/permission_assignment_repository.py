"""Acceso a datos de los permisos granulares asignados a un usuario."""

import uuid
from datetime import datetime

from sqlalchemy import select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from identity.users.enums.user_enums import PermissionEffect, UserScope
from identity.users.models.permission_assignment_model import PermissionAssignmentModel
from identity.users.models.permission_model import PermissionModel


class PermissionAssignmentRepository(
    SoftDeleteRepositoryBase[PermissionAssignmentModel]
):
    model_class = PermissionAssignmentModel

    async def get_overrides_for_user_org(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> list[tuple[str, PermissionEffect]]:
        result = await self.session.execute(
            select(PermissionModel.name, PermissionAssignmentModel.effect)
            .join(
                PermissionModel,
                PermissionAssignmentModel.permission_id == PermissionModel.id,
            )
            .where(
                PermissionAssignmentModel.user_id == user_id,
                PermissionAssignmentModel.organization_id == organization_id,
                PermissionAssignmentModel.is_active.is_(True),
                PermissionAssignmentModel.deleted_at.is_(None),
            )
        )
        return list(result.all())

    async def get_overrides_for_user_orgs(
        self, user_id: uuid.UUID, organization_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[str, PermissionEffect]]]:
        if not organization_ids:
            return {}
        result = await self.session.execute(
            select(
                PermissionAssignmentModel.organization_id,
                PermissionModel.name,
                PermissionAssignmentModel.effect,
            )
            .join(
                PermissionModel,
                PermissionAssignmentModel.permission_id == PermissionModel.id,
            )
            .where(
                PermissionAssignmentModel.user_id == user_id,
                PermissionAssignmentModel.organization_id.in_(organization_ids),
                PermissionAssignmentModel.is_active.is_(True),
                PermissionAssignmentModel.deleted_at.is_(None),
            )
        )
        overrides_by_org: dict[uuid.UUID, list[tuple[str, PermissionEffect]]] = {}
        for org_id, name, effect in result.all():
            overrides_by_org.setdefault(org_id, []).append((name, effect))
        return overrides_by_org

    async def get_permission_by_name(self, name: str) -> PermissionModel | None:
        result = await self.session.execute(
            select(PermissionModel).where(
                PermissionModel.name == name, PermissionModel.is_active.is_(True)
            )
        )
        return result.scalar_one_or_none()

    async def get_assignment(
        self, user_id: uuid.UUID, permission_id: uuid.UUID, organization_id: uuid.UUID
    ) -> PermissionAssignmentModel | None:
        result = await self.session.execute(
            select(PermissionAssignmentModel).where(
                PermissionAssignmentModel.user_id == user_id,
                PermissionAssignmentModel.permission_id == permission_id,
                PermissionAssignmentModel.organization_id == organization_id,
                PermissionAssignmentModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def upsert_for_org(
        self,
        user_id: uuid.UUID,
        permission_id: uuid.UUID,
        organization_id: uuid.UUID,
        effect: PermissionEffect,
    ) -> PermissionAssignmentModel:
        existing = await self.get_assignment(user_id, permission_id, organization_id)
        if existing:
            existing.effect = effect
            existing.is_active = True
            return await self.update(existing)
        return await self.add(
            PermissionAssignmentModel(
                user_id=user_id,
                permission_id=permission_id,
                scope=UserScope.ORGANIZATION,
                organization_id=organization_id,
                effect=effect,
            )
        )

    async def delete_for_org(
        self, user_id: uuid.UUID, permission_id: uuid.UUID, organization_id: uuid.UUID
    ) -> bool:
        existing = await self.get_assignment(user_id, permission_id, organization_id)
        if not existing:
            return False
        await self.delete(existing)
        return True

    async def get_all_active_permissions(self) -> list[PermissionModel]:
        result = await self.session.execute(
            select(PermissionModel)
            .where(PermissionModel.is_active.is_(True))
            .order_by(PermissionModel.name)
        )
        return list(result.scalars().all())

    async def get_user_ids_with_permission_in_org(
        self, organization_id: uuid.UUID, permission_name: str
    ) -> list[uuid.UUID]:
        result = await self.session.execute(
            select(PermissionAssignmentModel.user_id)
            .join(
                PermissionModel,
                PermissionAssignmentModel.permission_id == PermissionModel.id,
            )
            .where(
                PermissionModel.name == permission_name,
                PermissionAssignmentModel.organization_id == organization_id,
                PermissionAssignmentModel.effect == PermissionEffect.GRANT,
                PermissionAssignmentModel.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja de los permisos por usuario otorgados/revocados dentro de la
        organización."""
        await self.soft_delete_where(
            PermissionAssignmentModel.organization_id == organization_id,
            deleted_at=deleted_at,
        )

    async def restore_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        await self.restore_where(
            PermissionAssignmentModel.organization_id == organization_id,
            deleted_at=deleted_at,
        )
