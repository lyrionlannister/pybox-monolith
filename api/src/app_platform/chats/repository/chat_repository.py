"""Acceso a datos de chats y sus miembros."""

import uuid
from datetime import datetime

from sqlalchemy import select

from app_platform.chats.models.chat_member_model import ChatMemberModel
from app_platform.chats.models.chat_model import ChatModel
from core.base.soft_delete_repository_base import SoftDeleteRepositoryBase


class ChatRepository(SoftDeleteRepositoryBase[ChatModel]):
    model_class = ChatModel

    async def get_by_dm_key(self, dm_key: str) -> ChatModel | None:
        result = await self.session.execute(
            select(ChatModel).where(ChatModel.dm_key == dm_key)
        )
        return result.scalars().first()

    async def get_user_chats(self, user_id: uuid.UUID) -> list[ChatModel]:
        result = await self.session.execute(
            select(ChatModel)
            .join(ChatMemberModel, ChatMemberModel.chat_id == ChatModel.id)
            .where(
                ChatMemberModel.user_id == user_id,
                ChatMemberModel.left_at.is_(None),
            )
            .order_by(ChatModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def add_member(self, member: ChatMemberModel) -> ChatMemberModel:
        self.session.add(member)
        await self.session.flush()
        await self.session.refresh(member)
        return member

    async def add_members(self, members: list[ChatMemberModel]) -> None:
        """Alta en lote (un solo `flush`, sin `refresh` por fila): para cuando el
        llamador no necesita cada fila de vuelta, como al crear un grupo con varios
        miembros de una vez (ver `ChatService.create_group_chat`)."""
        self.session.add_all(members)
        await self.session.flush()

    async def get_member(
        self, chat_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatMemberModel | None:
        result = await self.session.execute(
            select(ChatMemberModel).where(
                ChatMemberModel.chat_id == chat_id,
                ChatMemberModel.user_id == user_id,
            )
        )
        return result.scalars().first()

    async def get_active_members(self, chat_id: uuid.UUID) -> list[ChatMemberModel]:
        result = await self.session.execute(
            select(ChatMemberModel).where(
                ChatMemberModel.chat_id == chat_id,
                ChatMemberModel.left_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_active_members_for_chats(
        self, chat_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[ChatMemberModel]]:
        if not chat_ids:
            return {}
        result = await self.session.execute(
            select(ChatMemberModel).where(
                ChatMemberModel.chat_id.in_(chat_ids),
                ChatMemberModel.left_at.is_(None),
            )
        )
        out: dict[uuid.UUID, list[ChatMemberModel]] = {}
        for member in result.scalars().all():
            out.setdefault(member.chat_id, []).append(member)
        return out

    async def set_member_left(
        self, chat_id: uuid.UUID, user_id: uuid.UUID, when: datetime
    ) -> None:
        member = await self.get_member(chat_id, user_id)
        if member is not None:
            member.left_at = when
            await self.session.flush()

    async def reactivate_member(
        self, chat_id: uuid.UUID, user_id: uuid.UUID, when: datetime
    ) -> ChatMemberModel:
        member = await self.get_member(chat_id, user_id)
        member.left_at = None
        member.joined_at = when
        await self.session.flush()
        await self.session.refresh(member)
        return member
