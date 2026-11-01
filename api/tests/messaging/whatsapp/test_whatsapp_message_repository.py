"""Tests de integración de WhatsAppMessageRepository (ver whatsapp_message_repository.py)."""

from datetime import datetime, timedelta, timezone

from messaging.whatsapp.enums.whatsapp_enums import MessageDirection
from messaging.whatsapp.repository.whatsapp_message_repository import (
    WhatsAppMessageRepository,
)
from tests.messaging.whatsapp.conftest import build_chat, build_message


class TestGetLastInbound:
    async def test_returns_most_recent_inbound_message(self, db_session, real_org):
        chat = build_chat(real_org.id)
        db_session.add(chat)
        await db_session.flush()
        now = datetime.now(timezone.utc)
        older = build_message(
            chat.id,
            direction=MessageDirection.INBOUND,
            sent_at=now - timedelta(hours=2),
        )
        newer = build_message(
            chat.id,
            direction=MessageDirection.INBOUND,
            sent_at=now - timedelta(minutes=5),
        )
        db_session.add_all([older, newer])
        await db_session.flush()
        repo = WhatsAppMessageRepository(db_session)

        result = await repo.get_last_inbound(chat.id)

        assert result.id == newer.id

    async def test_ignores_outbound_messages(self, db_session, real_org):
        chat = build_chat(real_org.id)
        db_session.add(chat)
        await db_session.flush()
        db_session.add(
            build_message(
                chat.id,
                direction=MessageDirection.OUTBOUND,
                sent_at=datetime.now(timezone.utc),
            )
        )
        await db_session.flush()
        repo = WhatsAppMessageRepository(db_session)

        assert await repo.get_last_inbound(chat.id) is None

    async def test_no_messages_returns_none(self, db_session, real_org):
        chat = build_chat(real_org.id)
        db_session.add(chat)
        await db_session.flush()
        repo = WhatsAppMessageRepository(db_session)

        assert await repo.get_last_inbound(chat.id) is None


class TestGetByWamid:
    async def test_finds_message_by_wamid(self, db_session, real_org):
        chat = build_chat(real_org.id)
        db_session.add(chat)
        await db_session.flush()
        message = build_message(chat.id, wamid="wamid.unico-123")
        db_session.add(message)
        await db_session.flush()
        repo = WhatsAppMessageRepository(db_session)

        result = await repo.get_by_wamid("wamid.unico-123")

        assert result is not None
        assert result.id == message.id

    async def test_unknown_wamid_returns_none(self, db_session):
        repo = WhatsAppMessageRepository(db_session)
        assert await repo.get_by_wamid("wamid.no-existe") is None


class TestListByChat:
    async def test_returns_messages_ordered_by_sent_at_ascending(
        self, db_session, real_org
    ):
        chat = build_chat(real_org.id)
        db_session.add(chat)
        await db_session.flush()
        now = datetime.now(timezone.utc)
        first = build_message(chat.id, sent_at=now - timedelta(minutes=10))
        second = build_message(chat.id, sent_at=now)
        db_session.add_all([second, first])  # insertados fuera de orden a propósito
        await db_session.flush()
        repo = WhatsAppMessageRepository(db_session)

        result = await repo.list_by_chat(chat.id)

        assert [m.id for m in result] == [first.id, second.id]

    async def test_caps_to_most_recent_messages_still_ascending(
        self, db_session, real_org
    ):
        """Hilo con más mensajes que el límite: se queda con los más recientes, pero
        la respuesta sigue en orden ascendente (más viejo primero) para mostrar."""
        chat = build_chat(real_org.id)
        db_session.add(chat)
        await db_session.flush()
        now = datetime.now(timezone.utc)
        messages = [
            build_message(chat.id, sent_at=now - timedelta(minutes=10 - i))
            for i in range(5)
        ]
        db_session.add_all(messages)
        await db_session.flush()
        repo = WhatsAppMessageRepository(db_session)

        result = await repo.list_by_chat(chat.id, limit=3)

        assert [m.id for m in result] == [m.id for m in messages[-3:]]

    async def test_only_returns_messages_of_requested_chat(self, db_session, real_org):
        chat_a = build_chat(real_org.id)
        chat_b = build_chat(real_org.id)
        db_session.add_all([chat_a, chat_b])
        await db_session.flush()
        db_session.add(build_message(chat_a.id))
        db_session.add(build_message(chat_b.id))
        await db_session.flush()
        repo = WhatsAppMessageRepository(db_session)

        result = await repo.list_by_chat(chat_a.id)

        assert len(result) == 1
        assert result[0].chat_id == chat_a.id
