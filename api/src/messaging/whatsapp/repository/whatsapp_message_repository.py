"""Acceso a datos de los mensajes de WhatsApp."""

import uuid
from datetime import datetime

from sqlalchemy import select

from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase
from messaging.whatsapp.enums.whatsapp_enums import MessageDirection
from messaging.whatsapp.models.whatsapp_chat_model import WhatsAppChatModel
from messaging.whatsapp.models.whatsapp_message_model import WhatsAppMessageModel


class WhatsAppMessageRepository(SoftDeleteRepositoryBase[WhatsAppMessageModel]):
    model_class = WhatsAppMessageModel

    async def get_last_inbound(self, chat_id: uuid.UUID) -> WhatsAppMessageModel | None:
        """Último mensaje ENTRANTE del hilo — determina si sigue abierta la ventana de
        servicio al cliente de 24h de Meta para poder enviar texto libre."""
        result = await self.session.execute(
            select(WhatsAppMessageModel)
            .where(
                WhatsAppMessageModel.chat_id == chat_id,
                WhatsAppMessageModel.direction == MessageDirection.INBOUND,
                WhatsAppMessageModel.deleted_at.is_(None),
            )
            .order_by(WhatsAppMessageModel.sent_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_wamid(self, wamid: str) -> WhatsAppMessageModel | None:
        result = await self.session.execute(
            select(WhatsAppMessageModel).where(
                WhatsAppMessageModel.wamid == wamid,
                WhatsAppMessageModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_chat(
        self, chat_id: uuid.UUID, limit: int = 200
    ) -> list[WhatsAppMessageModel]:
        """Los `limit` mensajes más recientes del hilo, en orden ascendente (igual
        que antes) -- sin tope, un hilo de larga duración (meses de conversación con
        un deudor) trae todos sus mensajes completos en cada apertura."""
        result = await self.session.execute(
            select(WhatsAppMessageModel)
            .where(
                WhatsAppMessageModel.chat_id == chat_id,
                WhatsAppMessageModel.deleted_at.is_(None),
            )
            .order_by(WhatsAppMessageModel.sent_at.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def soft_delete_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Baja en cascada de los mensajes de los chats de WhatsApp de la
        organización con el sello de la organización."""
        await self.soft_delete_where(
            WhatsAppMessageModel.chat_id.in_(
                select(WhatsAppChatModel.id).where(
                    WhatsAppChatModel.organization_id == organization_id
                )
            ),
            deleted_at=deleted_at,
        )

    async def restore_by_organization(
        self, organization_id: uuid.UUID, deleted_at: datetime
    ) -> None:
        """Inverso de ``soft_delete_by_organization``: solo lo que cayó
        con la organización."""
        await self.restore_where(
            WhatsAppMessageModel.chat_id.in_(
                select(WhatsAppChatModel.id).where(
                    WhatsAppChatModel.organization_id == organization_id
                )
            ),
            deleted_at=deleted_at,
        )
