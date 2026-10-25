"""Chats directos y grupales entre usuarios: mensajería, lectura y membresías."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app_platform.chats.enums.chat_enums import ChatType, MemberRole
from app_platform.chats.models.chat_member_model import ChatMemberModel
from app_platform.chats.models.chat_model import ChatModel
from app_platform.chats.models.message_model import MessageModel
from app_platform.chats.models.message_status_model import MessageStatusModel
from app_platform.chats.repository.chat_repository import ChatRepository
from app_platform.chats.repository.message_repository import MessageRepository
from app_platform.chats.schemas.chat_schemas import (
    ChatMemberSchema,
    ChatSummarySchema,
    MessageSchema,
    MessagesPageSchema,
)
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.users.models.user_model import UserModel
from identity.users.repository.role_assignment_repository import (
    RoleAssignmentRepository,
)
from identity.users.repository.user_repository import UserRepository
from identity.users.schemas.user_session_schema import UserSession


class ChatService:
    def __init__(
        self,
        chat_repo: ChatRepository,
        msg_repo: MessageRepository,
        user_repo: UserRepository,
        org_membership_repo: OrganizationMembershipRepository,
        role_assignment_repo: RoleAssignmentRepository,
    ):
        self.chat_repo = chat_repo
        self.msg_repo = msg_repo
        self.user_repo = user_repo
        self.org_membership_repo = org_membership_repo
        self.role_assignment_repo = role_assignment_repo

    async def find_or_create_direct_chat(
        self, user_a: uuid.UUID, user_b: uuid.UUID
    ) -> ChatSummarySchema:
        dm_key = ChatModel.build_dm_key(user_a, user_b)
        chat = await self.chat_repo.get_by_dm_key(dm_key)
        if not chat:
            chat = ChatModel(type=ChatType.DIRECT, dm_key=dm_key)
            chat = await self.chat_repo.add(chat)
            await self.chat_repo.add_member(
                ChatMemberModel(chat_id=chat.id, user_id=user_a, role=MemberRole.MEMBER)
            )
            await self.chat_repo.add_member(
                ChatMemberModel(chat_id=chat.id, user_id=user_b, role=MemberRole.MEMBER)
            )
        return await self._build_summary(chat, user_a)

    async def get_user_chats(self, user_id: uuid.UUID) -> list[ChatSummarySchema]:
        chats = await self.chat_repo.get_user_chats(user_id)
        if not chats:
            return []

        chat_ids = [chat.id for chat in chats]
        members_by_chat = await self.chat_repo.get_active_members_for_chats(chat_ids)
        last_messages_by_chat = await self.msg_repo.get_last_messages_for_chats(
            chat_ids
        )
        unread_by_chat = await self.msg_repo.get_unread_counts_for_chats(
            chat_ids, user_id
        )

        peer_user_ids = {
            member.user_id
            for chat in chats
            if chat.type == ChatType.DIRECT
            for member in members_by_chat.get(chat.id, [])
            if member.user_id != user_id
        }
        peer_users = await self.user_repo.get_by_ids(list(peer_user_ids))

        return [
            self._build_summary_from_batches(
                chat,
                user_id,
                members_by_chat,
                last_messages_by_chat,
                unread_by_chat,
                peer_users,
            )
            for chat in chats
        ]

    def _build_summary_from_batches(
        self,
        chat,
        user_id: uuid.UUID,
        members_by_chat: dict[uuid.UUID, list[ChatMemberModel]],
        last_messages_by_chat: dict[uuid.UUID, MessageModel],
        unread_by_chat: dict[uuid.UUID, int],
        peer_users: dict[uuid.UUID, UserModel],
    ) -> ChatSummarySchema:
        title = chat.title or ""
        peer_id = None
        peer_avatar = None

        if chat.type == ChatType.DIRECT:
            members = members_by_chat.get(chat.id, [])
            peer_member = next((m for m in members if m.user_id != user_id), None)
            peer_user = peer_users.get(peer_member.user_id) if peer_member else None
            if peer_user:
                title = peer_user.full_name
                peer_id = peer_user.id
                peer_avatar = peer_user.profile_photo_url

        last_msg = last_messages_by_chat.get(chat.id)
        unread = unread_by_chat.get(chat.id, 0)
        member_count = len(members_by_chat.get(chat.id, []))

        return ChatSummarySchema(
            id=chat.id,
            type=chat.type,
            title=title,
            peer_id=peer_id,
            peer_avatar=peer_avatar,
            member_count=member_count,
            last_message=last_msg.body if last_msg else None,
            last_message_at=last_msg.created_at if last_msg else None,
            unread_count=unread,
        )

    async def _build_summary(self, chat, user_id: uuid.UUID) -> ChatSummarySchema:
        title = chat.title or ""
        peer_id = None
        peer_avatar = None

        members = await self.chat_repo.get_active_members(chat.id)

        if chat.type == ChatType.DIRECT:
            peer_member = next((m for m in members if m.user_id != user_id), None)
            if peer_member:
                peer_user = await self.user_repo.get_by_id(peer_member.user_id)
                if peer_user:
                    title = peer_user.full_name
                    peer_id = peer_user.id
                    peer_avatar = peer_user.profile_photo_url

        last_msg = await self.msg_repo.get_last_message(chat.id)
        unread = await self.msg_repo.get_unread_count(chat.id, user_id)

        return ChatSummarySchema(
            id=chat.id,
            type=chat.type,
            title=title,
            peer_id=peer_id,
            peer_avatar=peer_avatar,
            member_count=len(members),
            last_message=last_msg.body if last_msg else None,
            last_message_at=last_msg.created_at if last_msg else None,
            unread_count=unread,
        )

    async def assert_member(self, chat_id: uuid.UUID, user_id: uuid.UUID) -> None:
        member = await self.chat_repo.get_member(chat_id, user_id)
        if not member or member.left_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No eres miembro de este chat.",
            )

    async def send_message(
        self, chat_id: uuid.UUID, sender_id: uuid.UUID, body: str
    ) -> tuple[MessageSchema, list[uuid.UUID]]:
        await self.assert_member(chat_id, sender_id)

        body = body.strip()
        if not body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El mensaje no puede estar vacío.",
            )

        msg = MessageModel(chat_id=chat_id, sender_id=sender_id, body=body)
        msg = await self.msg_repo.add(msg)

        now = datetime.now(timezone.utc)
        members = await self.chat_repo.get_active_members(chat_id)
        member_ids = [m.user_id for m in members]

        statuses = [
            MessageStatusModel(
                message_id=msg.id,
                user_id=uid,
                delivered_at=now,
                read_at=now if uid == sender_id else None,
            )
            for uid in member_ids
        ]
        await self.msg_repo.add_statuses(statuses)

        sender = await self.user_repo.get_by_id(sender_id)
        msg_schema = MessageSchema(
            id=msg.id,
            chat_id=chat_id,
            sender_id=sender_id,
            sender_name=sender.full_name if sender else "Usuario",
            sender_avatar=sender.profile_photo_url if sender else None,
            body=msg.body,
            created_at=msg.created_at,
            status="sent",
        )
        other_ids = [uid for uid in member_ids if uid != sender_id]
        return msg_schema, other_ids

    async def list_messages(
        self,
        chat_id: uuid.UUID,
        user_id: uuid.UUID,
        before_ts: str | None,
        limit: int,
    ) -> MessagesPageSchema:
        await self.assert_member(chat_id, user_id)

        before_dt = datetime.fromisoformat(before_ts) if before_ts else None
        rows = await self.msg_repo.get_chat_messages(chat_id, before_dt, limit + 1)

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        if not rows:
            return MessagesPageSchema(items=[], next_cursor=None)

        statuses_map = await self.msg_repo.get_statuses_for_messages(
            [m.id for m in rows]
        )

        sender_ids = list({m.sender_id for m in rows})
        sender_cache = await self.user_repo.get_by_ids(sender_ids)
        items: list[MessageSchema] = []

        for msg in rows:
            sender = sender_cache.get(msg.sender_id)

            msg_statuses = statuses_map.get(msg.id, [])
            other = [s for s in msg_statuses if s.user_id != msg.sender_id]
            if other and all(s.read_at for s in other):
                msg_status = "read"
            elif other and all(s.delivered_at for s in other):
                msg_status = "delivered"
            else:
                msg_status = "sent"

            items.append(
                MessageSchema(
                    id=msg.id,
                    chat_id=msg.chat_id,
                    sender_id=msg.sender_id,
                    sender_name=sender.full_name if sender else "Usuario",
                    sender_avatar=sender.profile_photo_url if sender else None,
                    body=msg.body,
                    created_at=msg.created_at,
                    status=msg_status,
                )
            )

        items.reverse()
        next_cursor = rows[-1].created_at.isoformat() if has_more else None
        return MessagesPageSchema(items=items, next_cursor=next_cursor)

    async def mark_read(
        self, chat_id: uuid.UUID, user_id: uuid.UUID, message_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]:
        await self.assert_member(chat_id, user_id)
        now = datetime.now(timezone.utc)
        await self.msg_repo.mark_read_many(message_ids, user_id, now)
        members = await self.chat_repo.get_active_members(chat_id)
        return [m.user_id for m in members if m.user_id != user_id]

    async def mark_all_read(
        self, chat_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
        await self.assert_member(chat_id, user_id)
        now = datetime.now(timezone.utc)
        unread_ids = await self.msg_repo.get_unread_message_ids(chat_id, user_id)
        await self.msg_repo.mark_all_read(chat_id, user_id, now)
        members = await self.chat_repo.get_active_members(chat_id)
        other_ids = [m.user_id for m in members if m.user_id != user_id]
        return other_ids, unread_ids

    async def _resolve_pinned_organization(
        self,
        actor_session: UserSession,
        existing_org_id: uuid.UUID | None,
        candidate_ids: set[uuid.UUID],
    ) -> uuid.UUID | None:
        """Deriva a qué organización queda pineado un grupo, sin confiar nunca en un
        organization_id que venga del cliente. Regla: GLOBAL siempre elegible; un
        candidato ORGANIZATION-scoped solo es elegible si su organización coincide con
        `existing_org_id` (grupo ya pineado) o, si el grupo sigue sin pinear, con las
        organizaciones reales del propio actor (o con las de los demás candidatos, si
        el actor es GLOBAL). Un candidato sin organización ni scope GLOBAL (deudor
        SELF) nunca resuelve un scope válido y cae en el 400 genérico."""
        if existing_org_id is not None:
            common: set[uuid.UUID] | None = {existing_org_id}
        elif not actor_session.is_global:
            common = {uuid.UUID(oid) for oid in actor_session.orgs}
        else:
            common = None

        global_ids = await self.role_assignment_repo.get_global_user_ids(
            list(candidate_ids)
        )
        non_global = candidate_ids - global_ids
        if not non_global:
            return existing_org_id

        memberships = await self.org_membership_repo.get_by_user_ids(list(non_global))
        org_ids_by_user: dict[uuid.UUID, set[uuid.UUID]] = {}
        for m in memberships:
            org_ids_by_user.setdefault(m.user_id, set()).add(m.organization_id)

        for uid in non_global:
            candidate_orgs = org_ids_by_user.get(uid, set())
            common = candidate_orgs if common is None else common & candidate_orgs
            if not common:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Los miembros de un grupo deben pertenecer a la misma "
                    "organización (o ser del equipo global).",
                )

        return existing_org_id or next(iter(sorted(common)))

    async def _require_group_admin(
        self, chat_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatMemberModel:
        member = await self.chat_repo.get_member(chat_id, user_id)
        if not member or member.left_at is not None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No eres miembro de este chat."
            )
        if member.role not in (MemberRole.ADMIN, MemberRole.OWNER):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Solo un administrador del grupo puede realizar esta acción.",
            )
        return member

    async def _require_group_chat(self, chat_id: uuid.UUID):
        chat = await self.chat_repo.get_by_id(chat_id)
        if not chat or chat.type != ChatType.GROUP:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo no encontrado.")
        return chat

    async def create_group_chat(
        self, actor_session: UserSession, title: str, member_ids: list[uuid.UUID]
    ) -> ChatSummarySchema:
        title = title.strip()
        if not title:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "El grupo necesita un nombre."
            )

        others = {uid for uid in member_ids if uid != actor_session.user_id}
        if not others:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Selecciona al menos un miembro más."
            )

        all_ids = others | {actor_session.user_id}
        organization_id = await self._resolve_pinned_organization(
            actor_session, None, all_ids
        )

        chat = ChatModel(
            type=ChatType.GROUP, title=title, organization_id=organization_id
        )
        chat = await self.chat_repo.add(chat)

        await self.chat_repo.add_member(
            ChatMemberModel(
                chat_id=chat.id, user_id=actor_session.user_id, role=MemberRole.OWNER
            )
        )
        for uid in others:
            await self.chat_repo.add_member(
                ChatMemberModel(chat_id=chat.id, user_id=uid, role=MemberRole.MEMBER)
            )

        return await self._build_summary(chat, actor_session.user_id)

    async def add_member(
        self, actor_session: UserSession, chat_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> tuple[ChatSummarySchema, list[uuid.UUID]]:
        chat = await self._require_group_chat(chat_id)
        await self._require_group_admin(chat_id, actor_session.user_id)

        existing = await self.chat_repo.get_member(chat_id, candidate_id)
        if existing and existing.left_at is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Ese usuario ya es miembro del grupo."
            )

        organization_id = await self._resolve_pinned_organization(
            actor_session, chat.organization_id, {candidate_id}
        )
        if organization_id != chat.organization_id:
            chat.organization_id = organization_id
            chat = await self.chat_repo.update(chat)

        now = datetime.now(timezone.utc)
        if existing:
            await self.chat_repo.reactivate_member(chat_id, candidate_id, now)
        else:
            await self.chat_repo.add_member(
                ChatMemberModel(
                    chat_id=chat_id, user_id=candidate_id, role=MemberRole.MEMBER
                )
            )

        members = await self.chat_repo.get_active_members(chat_id)
        other_ids = [m.user_id for m in members if m.user_id != candidate_id]
        summary = await self._build_summary(chat, actor_session.user_id)
        return summary, other_ids

    async def remove_member(
        self, actor_session: UserSession, chat_id: uuid.UUID, target_id: uuid.UUID
    ) -> list[uuid.UUID]:
        await self._require_group_chat(chat_id)
        actor_id = actor_session.user_id

        target_member = await self.chat_repo.get_member(chat_id, target_id)
        if not target_member or target_member.left_at is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Ese usuario no es miembro del grupo."
            )

        if target_id != actor_id:
            actor_member = await self._require_group_admin(chat_id, actor_id)
            if (
                target_member.role == MemberRole.OWNER
                and actor_member.role != MemberRole.OWNER
            ):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "Solo el propietario del grupo puede removerlo.",
                )

        members_before = await self.chat_repo.get_active_members(chat_id)
        recipient_ids = [m.user_id for m in members_before if m.user_id != target_id]
        await self.chat_repo.set_member_left(
            chat_id, target_id, datetime.now(timezone.utc)
        )
        return recipient_ids

    async def get_chat_summary_for(
        self, chat_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatSummarySchema:
        chat = await self._require_group_chat(chat_id)
        return await self._build_summary(chat, user_id)

    async def list_members(
        self, chat_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[ChatMemberSchema]:
        await self.assert_member(chat_id, user_id)
        members = await self.chat_repo.get_active_members(chat_id)
        users = await self.user_repo.get_by_ids([m.user_id for m in members])
        return [
            ChatMemberSchema(
                user_id=m.user_id,
                full_name=(
                    users[m.user_id].full_name if m.user_id in users else "Usuario"
                ),
                profile_photo_url=(
                    users[m.user_id].profile_photo_url if m.user_id in users else None
                ),
                role=m.role,
            )
            for m in members
        ]
