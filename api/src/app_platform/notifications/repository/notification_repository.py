"""Acceso a datos de las notificaciones in-app de un usuario."""

import uuid
from typing import Sequence

from sqlalchemy import select, update

from app_platform.notifications.models.notification_model import NotificationModel
from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase


class NotificationRepository(SoftDeleteRepositoryBase[NotificationModel]):
    model_class = NotificationModel

    async def get_by_user_id(
        self, user_id: uuid.UUID, limit: int = 200
    ) -> Sequence[NotificationModel]:
        result = await self.session.execute(
            select(NotificationModel)
            .where(NotificationModel.user_id == user_id)
            .order_by(NotificationModel.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_by_id_and_user(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> NotificationModel | None:
        result = await self.session.execute(
            select(NotificationModel).where(
                NotificationModel.id == notification_id,
                NotificationModel.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_all_read(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            update(NotificationModel)
            .where(
                NotificationModel.user_id == user_id,
                NotificationModel.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self.session.flush()
