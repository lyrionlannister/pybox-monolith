"""Tests de `ContactRepository` contra la base de datos real (sin mocks), mismo
patrón que `tests/receivables/test_credit_repository.py`. Cubre las queries usadas
para reconciliación de resultados (`get_by_external_id`, `get_by_sending_id`), el
prefetch de sendings pendientes de reconciliar (`get_pending_sending_ids` -- solo
NRS360 + status SENT, filtrado por proveedor y estado), y el conteo de envíos por
estado (`get_send_status_counts`).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from messaging.channels.enums.channel_enums import ChannelName
from messaging.channels.models.channel_model import ChannelModel
from messaging.contacts.enums.contact_enums import ContactStatus, ProviderType
from messaging.contacts.models.contact_model import ContactModel
from messaging.contacts.repository.contact_repository import ContactRepository
from tests.receivables.conftest import build_debtor, build_organization


async def _channel_id(db_session, name: ChannelName) -> uuid.UUID:
    result = await db_session.execute(
        select(ChannelModel.id).where(ChannelModel.name == name)
    )
    return result.scalar_one()


def make_contact(**overrides) -> ContactModel:
    defaults = dict(
        content="hola",
        recipient=overrides.pop("recipient", "+573001112233"),
        status=overrides.pop("status", ContactStatus.PENDING),
    )
    defaults.update(overrides)
    return ContactModel(**defaults)


class TestGetByExternalId:
    async def test_finds_contact_by_external_id(self, db_session):
        repo = ContactRepository(db_session)
        contact = make_contact(external_id="wamid.abc123")
        db_session.add(contact)
        await db_session.flush()

        result = await repo.get_by_external_id("wamid.abc123")

        assert result is not None
        assert result.id == contact.id

    async def test_unknown_external_id_returns_none(self, db_session):
        repo = ContactRepository(db_session)
        assert await repo.get_by_external_id("no-existe") is None


class TestGetBySendingId:
    async def test_returns_all_contacts_sharing_the_sending_id(self, db_session):
        repo = ContactRepository(db_session)
        db_session.add_all(
            [
                make_contact(sending_id="sending-1", recipient="+573001112233"),
                make_contact(sending_id="sending-1", recipient="+573001112244"),
                make_contact(sending_id="sending-2", recipient="+573001112255"),
            ]
        )
        await db_session.flush()

        results = await repo.get_by_sending_id("sending-1")

        assert len(results) == 2
        assert {c.recipient for c in results} == {"+573001112233", "+573001112244"}


class TestGetPendingSendingIds:
    async def test_only_nrs360_sent_contacts_with_sending_id_are_included(
        self, db_session
    ):
        repo = ContactRepository(db_session)
        sms_channel_id = await _channel_id(db_session, ChannelName.SMS)

        pending = make_contact(
            sending_id="sending-pending",
            status=ContactStatus.SENT,
            provider=ProviderType.NRS360,
            snapshot_channel_id=sms_channel_id,
        )
        # No debe aparecer: ya reconciliado (status DELIVERED, no SENT).
        already_reconciled = make_contact(
            sending_id="sending-done",
            status=ContactStatus.DELIVERED,
            provider=ProviderType.NRS360,
            snapshot_channel_id=sms_channel_id,
        )
        # No debe aparecer: proveedor distinto (WhatsApp Cloud no usa este flujo).
        wrong_provider = make_contact(
            sending_id="sending-wa",
            status=ContactStatus.SENT,
            provider=ProviderType.WHATSAPP_CLOUD,
            snapshot_channel_id=sms_channel_id,
        )
        db_session.add_all([pending, already_reconciled, wrong_provider])
        await db_session.flush()

        results = await repo.get_pending_sending_ids()

        sending_ids = {sending_id for sending_id, _ in results}
        assert "sending-pending" in sending_ids
        assert "sending-done" not in sending_ids
        assert "sending-wa" not in sending_ids


class TestGetSendStatusCounts:
    async def test_counts_are_grouped_by_status_within_the_organization(
        self, db_session
    ):
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        repo = ContactRepository(db_session)

        db_session.add_all(
            [
                make_contact(status=ContactStatus.SENT, organization_id=org.id),
                make_contact(status=ContactStatus.SENT, organization_id=org.id),
                make_contact(status=ContactStatus.FAILED, organization_id=org.id),
            ]
        )
        await db_session.flush()

        counts = dict(await repo.get_send_status_counts(org.id))

        assert counts[str(ContactStatus.SENT)] == 2
        assert counts[str(ContactStatus.FAILED)] == 1

    async def test_other_organizations_are_not_counted(self, db_session):
        org_a = build_organization()
        org_b = build_organization()
        db_session.add_all([org_a, org_b])
        await db_session.flush()
        repo = ContactRepository(db_session)

        db_session.add_all(
            [
                make_contact(status=ContactStatus.SENT, organization_id=org_a.id),
                make_contact(status=ContactStatus.SENT, organization_id=org_b.id),
            ]
        )
        await db_session.flush()

        counts = dict(await repo.get_send_status_counts(org_a.id))

        assert counts[str(ContactStatus.SENT)] == 1


class TestMarkFailedIfSentBulk:
    async def test_sets_updated_at(self, db_session):
        repo = ContactRepository(db_session)
        contact = make_contact(status=ContactStatus.SENT)
        db_session.add(contact)
        await db_session.flush()

        await repo.mark_failed_if_sent_bulk([contact.id])
        await db_session.refresh(contact)

        assert contact.status == ContactStatus.FAILED
        assert contact.updated_at is not None

    async def test_skips_contacts_not_in_sent_status(self, db_session):
        repo = ContactRepository(db_session)
        contact = make_contact(status=ContactStatus.DELIVERED)
        db_session.add(contact)
        await db_session.flush()

        await repo.mark_failed_if_sent_bulk([contact.id])
        await db_session.refresh(contact)

        assert contact.status == ContactStatus.DELIVERED


class TestGetLatestByRecipientAndOrg:
    async def test_returns_the_most_recently_created_contact(self, db_session):
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        debtor = build_debtor(org.id)
        db_session.add(debtor)
        await db_session.flush()
        repo = ContactRepository(db_session)

        older = make_contact(
            recipient="+573001112233", organization_id=org.id, debtor_id=debtor.id
        )
        db_session.add(older)
        await db_session.flush()

        newer = make_contact(
            recipient="+573001112233", organization_id=org.id, debtor_id=debtor.id
        )
        db_session.add(newer)
        await db_session.flush()
        # Fuerza el orden esperado sin depender de la resolución del reloj entre inserts.
        older.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db_session.flush()

        result = await repo.get_latest_by_recipient_and_org("+573001112233", org.id)

        assert result is not None
        assert result.id == newer.id

    async def test_contacts_without_debtor_id_are_excluded(self, db_session):
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        repo = ContactRepository(db_session)

        contact = make_contact(
            recipient="+573009998877", organization_id=org.id, debtor_id=None
        )
        db_session.add(contact)
        await db_session.flush()

        result = await repo.get_latest_by_recipient_and_org("+573009998877", org.id)

        assert result is None
