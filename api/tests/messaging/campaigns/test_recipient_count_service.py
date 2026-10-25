"""Tests unitarios de `RecipientCountService` (ver recipient_count_service.py):
conteo de destinatarios vigentes de una campaña, resolviendo su segmento en vivo
y agrupando campañas que comparten segmento+tipo de contacto para no repetir la
consulta cara del DML. Repos mockeados con AsyncMock/MagicMock; la caché usa el
`cache_service` real contra el Redis fake (`fake_redis`, autouse en conftest) para
probar el TTL/reuso real, no solo que se llamó un mock.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

from messaging.campaigns.services.recipient_count_service import RecipientCountService
from messaging.channels.enums.channel_enums import ChannelName
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType


def make_service():
    segment_repo = AsyncMock()
    channel_repo = AsyncMock()
    contact_method_repo = AsyncMock()
    dml = AsyncMock()
    portfolio_repo = AsyncMock()
    service = RecipientCountService(
        segment_repo, channel_repo, contact_method_repo, dml, portfolio_repo
    )
    return service, segment_repo, channel_repo, contact_method_repo, dml, portfolio_repo


def make_campaign(**overrides) -> MagicMock:
    defaults = dict(id=uuid.uuid4(), segment_id=uuid.uuid4(), channel_id=uuid.uuid4())
    defaults.update(overrides)
    campaign = MagicMock()
    for key, value in defaults.items():
        setattr(campaign, key, value)
    return campaign


def make_channel(name: ChannelName, channel_id: uuid.UUID | None = None) -> MagicMock:
    channel = MagicMock()
    channel.id = channel_id or uuid.uuid4()
    channel.name = name
    return channel


def make_segment(portfolio_id: uuid.UUID, **criteria_overrides) -> MagicMock:
    criteria = {"tables": [{"name": "deudores"}]}
    criteria.update(criteria_overrides)
    segment = MagicMock()
    segment.portfolio_id = portfolio_id
    segment.filter_criteria = criteria
    return segment


def dml_success(rows: list[dict]) -> dict:
    return {"success": True, "data": json.dumps(rows)}


class TestCountForCampaignsGrouping:
    async def test_campaigns_sharing_segment_and_contact_type_reuse_one_count(self):
        (
            service,
            segment_repo,
            channel_repo,
            contact_method_repo,
            dml,
            portfolio_repo,
        ) = make_service()
        segment_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        # SMS y WhatsApp caen ambos en ContactMethodType.PHONE -- deben agruparse.
        campaign_sms = make_campaign(segment_id=segment_id, channel_id=uuid.uuid4())
        campaign_whatsapp = make_campaign(
            segment_id=segment_id, channel_id=uuid.uuid4()
        )

        channel_repo.get_all = AsyncMock(
            return_value=[
                make_channel(ChannelName.SMS, campaign_sms.channel_id),
                make_channel(ChannelName.WHATSAPP, campaign_whatsapp.channel_id),
            ]
        )
        segment_repo.get_by_id = AsyncMock(return_value=make_segment(portfolio_id))
        portfolio_repo.get_by_id = AsyncMock(
            return_value=MagicMock(organization_id=uuid.uuid4())
        )
        debtor_id = uuid.uuid4()
        dml.execute_query = AsyncMock(
            return_value=dml_success([{"id": str(debtor_id)}])
        )
        contact_method_repo.get_all_values_by_debtors = AsyncMock(
            return_value={debtor_id: ["3001234567"]}
        )

        counts = await service.count_for_campaigns([campaign_sms, campaign_whatsapp])

        assert counts[campaign_sms.id] == 1
        assert counts[campaign_whatsapp.id] == 1
        # Un solo segmento resuelto pese a 2 campañas -- esa es la optimización.
        dml.execute_query.assert_awaited_once()

    async def test_campaigns_with_different_segments_are_counted_separately(self):
        (
            service,
            segment_repo,
            channel_repo,
            contact_method_repo,
            dml,
            portfolio_repo,
        ) = make_service()
        portfolio_id = uuid.uuid4()
        campaign_a = make_campaign()
        campaign_b = make_campaign()

        channel_repo.get_all = AsyncMock(
            return_value=[
                make_channel(ChannelName.SMS, campaign_a.channel_id),
                make_channel(ChannelName.SMS, campaign_b.channel_id),
            ]
        )
        segment_repo.get_by_id = AsyncMock(return_value=make_segment(portfolio_id))
        portfolio_repo.get_by_id = AsyncMock(
            return_value=MagicMock(organization_id=uuid.uuid4())
        )
        dml.execute_query = AsyncMock(
            return_value=dml_success([{"id": str(uuid.uuid4())}])
        )
        contact_method_repo.get_all_values_by_debtors = AsyncMock(return_value={})

        await service.count_for_campaigns([campaign_a, campaign_b])

        assert dml.execute_query.await_count == 2


class TestCountForCampaignsZeroCases:
    async def test_campaign_without_segment_counts_zero_without_touching_repos(self):
        (
            service,
            segment_repo,
            channel_repo,
            contact_method_repo,
            dml,
            portfolio_repo,
        ) = make_service()
        campaign = make_campaign(segment_id=None)

        counts = await service.count_for_campaigns([campaign])

        assert counts == {campaign.id: 0}
        channel_repo.get_all.assert_not_awaited()
        dml.execute_query.assert_not_awaited()

    async def test_unknown_channel_counts_zero(self):
        (
            service,
            segment_repo,
            channel_repo,
            contact_method_repo,
            dml,
            portfolio_repo,
        ) = make_service()
        campaign = make_campaign()
        channel_repo.get_all = AsyncMock(return_value=[])

        counts = await service.count_for_campaigns([campaign])

        assert counts == {campaign.id: 0}
        dml.execute_query.assert_not_awaited()

    async def test_segment_not_found_counts_zero(self):
        (
            service,
            segment_repo,
            channel_repo,
            contact_method_repo,
            dml,
            portfolio_repo,
        ) = make_service()
        campaign = make_campaign()
        channel_repo.get_all = AsyncMock(
            return_value=[make_channel(ChannelName.SMS, campaign.channel_id)]
        )
        segment_repo.get_by_id = AsyncMock(return_value=None)

        counts = await service.count_for_campaigns([campaign])

        assert counts == {campaign.id: 0}

    async def test_dml_failure_counts_zero(self):
        (
            service,
            segment_repo,
            channel_repo,
            contact_method_repo,
            dml,
            portfolio_repo,
        ) = make_service()
        campaign = make_campaign()
        channel_repo.get_all = AsyncMock(
            return_value=[make_channel(ChannelName.SMS, campaign.channel_id)]
        )
        segment_repo.get_by_id = AsyncMock(return_value=make_segment(uuid.uuid4()))
        portfolio_repo.get_by_id = AsyncMock(
            return_value=MagicMock(organization_id=uuid.uuid4())
        )
        dml.execute_query = AsyncMock(return_value={"success": False, "error": "boom"})

        counts = await service.count_for_campaigns([campaign])

        assert counts == {campaign.id: 0}

    async def test_no_debtor_ids_extracted_counts_zero_without_calling_contact_repo(
        self,
    ):
        (
            service,
            segment_repo,
            channel_repo,
            contact_method_repo,
            dml,
            portfolio_repo,
        ) = make_service()
        campaign = make_campaign()
        channel_repo.get_all = AsyncMock(
            return_value=[make_channel(ChannelName.SMS, campaign.channel_id)]
        )
        segment_repo.get_by_id = AsyncMock(return_value=make_segment(uuid.uuid4()))
        portfolio_repo.get_by_id = AsyncMock(
            return_value=MagicMock(organization_id=uuid.uuid4())
        )
        dml.execute_query = AsyncMock(return_value=dml_success([]))

        counts = await service.count_for_campaigns([campaign])

        assert counts == {campaign.id: 0}
        contact_method_repo.get_all_values_by_debtors.assert_not_awaited()


class TestCountDeduplicatesContactValues:
    async def test_duplicate_contact_values_across_debtors_are_counted_once(self):
        (
            service,
            segment_repo,
            channel_repo,
            contact_method_repo,
            dml,
            portfolio_repo,
        ) = make_service()
        campaign = make_campaign()
        debtor_a, debtor_b = uuid.uuid4(), uuid.uuid4()
        channel_repo.get_all = AsyncMock(
            return_value=[make_channel(ChannelName.SMS, campaign.channel_id)]
        )
        segment_repo.get_by_id = AsyncMock(return_value=make_segment(uuid.uuid4()))
        portfolio_repo.get_by_id = AsyncMock(
            return_value=MagicMock(organization_id=uuid.uuid4())
        )
        dml.execute_query = AsyncMock(
            return_value=dml_success([{"id": str(debtor_a)}, {"id": str(debtor_b)}])
        )
        # Mismo numero de telefono importado en dos deudores distintos (dato sucio real).
        contact_method_repo.get_all_values_by_debtors = AsyncMock(
            return_value={
                debtor_a: ["3001234567"],
                debtor_b: ["3001234567", "3009999999"],
            }
        )

        counts = await service.count_for_campaigns([campaign])

        assert counts[campaign.id] == 2  # 3001234567 (deduplicado) + 3009999999


class TestCountCaching:
    async def test_second_call_for_same_segment_and_contact_type_hits_cache_not_dml(
        self,
    ):
        (
            service,
            segment_repo,
            channel_repo,
            contact_method_repo,
            dml,
            portfolio_repo,
        ) = make_service()
        segment_id = uuid.uuid4()
        campaign1 = make_campaign(segment_id=segment_id)
        campaign2 = make_campaign(segment_id=segment_id)
        channel_repo.get_all = AsyncMock(
            return_value=[
                make_channel(ChannelName.SMS, campaign1.channel_id),
                make_channel(ChannelName.SMS, campaign2.channel_id),
            ]
        )
        segment_repo.get_by_id = AsyncMock(return_value=make_segment(uuid.uuid4()))
        portfolio_repo.get_by_id = AsyncMock(
            return_value=MagicMock(organization_id=uuid.uuid4())
        )
        dml.execute_query = AsyncMock(
            return_value=dml_success([{"id": str(uuid.uuid4())}])
        )
        contact_method_repo.get_all_values_by_debtors = AsyncMock(return_value={})

        # Primera llamada -- dos campañas del MISMO segmento en una sola invocación ya
        # se agrupan (test aparte); acá se separan en dos llamadas a count_for_campaigns
        # para probar la caché de Redis entre invocaciones distintas del servicio.
        await service.count_for_campaigns([campaign1])
        assert dml.execute_query.await_count == 1

        await service.count_for_campaigns([campaign2])
        # Segunda invocación: mismo segmento+tipo de contacto -- debe salir de la caché
        # de Redis (TTL 120s), no volver a golpear el DML.
        assert dml.execute_query.await_count == 1
