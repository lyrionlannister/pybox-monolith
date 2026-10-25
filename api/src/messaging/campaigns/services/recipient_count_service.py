"""Cuenta destinatarios únicos de una campaña antes de enviarla."""

import json
import uuid

from pydantic import TypeAdapter

from app_platform.schema_manager.services.dml_service import DmlService
from core.cache.cache_service import cache_service
from core.config.logger import logger
from messaging.campaigns.constants.channel_contact_constants import CHANNEL_CONTACT_TYPE
from messaging.campaigns.models.campaign_model import CampaignModel
from messaging.campaigns.utils.segment_utils import extract_debtor_ids
from messaging.channels.models.channel_model import ChannelModel
from messaging.channels.repository.channel_repository import ChannelRepository
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType
from receivables.contact_methods.repository.contact_method_repository import (
    ContactMethodRepository,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.segments.repository.segment_repository import SegmentRepository

_count_adapter: TypeAdapter[int] = TypeAdapter(int)


class RecipientCountService:
    """Cuenta los destinatarios de una campaña resolviendo su segmento en vivo.

    ``campanas.total_destinatarios`` solo se escribe al crear la campaña,
    así que no refleja el segmento actual. El conteo replica la
    resolución que hace ``AutomationService`` al enviar (deudores del
    segmento → contacto del canal → deduplicado por valor de contacto)
    para que el número coincida con lo que se enviaría si la campaña se
    ejecutara en este momento.
    """

    def __init__(
        self,
        segment_repo: SegmentRepository,
        channel_repo: ChannelRepository,
        contact_method_repo: ContactMethodRepository,
        dml: DmlService,
        portfolio_repo: PortfolioRepository,
    ) -> None:
        self._segment_repo = segment_repo
        self._channel_repo = channel_repo
        self._contact_method_repo = contact_method_repo
        self._dml = dml
        self._portfolio_repo = portfolio_repo

    async def count_for_campaigns(
        self, campaigns: list[CampaignModel]
    ) -> dict[uuid.UUID, int]:
        """Destinatarios por campaña, resolviendo cada segmento una sola vez.

        Ejecutar el segmento es caro, así que las campañas que comparten
        segmento y tipo de contacto se agrupan: varios canales caen en el
        mismo tipo (SMS/WhatsApp/llamada → teléfono) y por tanto en el
        mismo conteo.
        """
        counts: dict[uuid.UUID, int] = {}
        groups: dict[tuple[uuid.UUID, ContactMethodType], list[uuid.UUID]] = {}
        channels_by_id = (
            {c.id: c for c in await self._channel_repo.get_all()}
            if any(c.segment_id is not None for c in campaigns)
            else {}
        )

        for campaign in campaigns:
            key = self._group_key(campaign, channels_by_id)
            if key is None:
                counts[campaign.id] = 0
                continue
            groups.setdefault(key, []).append(campaign.id)

        for (segment_id, contact_type), campaign_ids in groups.items():
            count = await self._count(segment_id, contact_type)
            for campaign_id in campaign_ids:
                counts[campaign_id] = count

        return counts

    def _group_key(
        self,
        campaign: CampaignModel,
        channels_by_id: dict[uuid.UUID, ChannelModel],
    ) -> tuple[uuid.UUID, ContactMethodType] | None:
        if campaign.segment_id is None:
            return None

        channel = channels_by_id.get(campaign.channel_id)
        if channel is None:
            logger.warning(
                "[recipient_count] campaña %s: canal %s no encontrado",
                campaign.id,
                campaign.channel_id,
            )
            return None

        contact_type = CHANNEL_CONTACT_TYPE.get(channel.name)
        if contact_type is None:
            logger.warning(
                "[recipient_count] campaña %s: canal %s sin tipo de contacto asociado",
                campaign.id,
                channel.name,
            )
            return None

        return campaign.segment_id, contact_type

    async def _count(
        self, segment_id: uuid.UUID, contact_type: ContactMethodType
    ) -> int:
        return await cache_service.get_or_set(
            key=f"campaign:recipient-count:{segment_id}:{contact_type.value}",
            fetch=lambda: self._count_from_db(segment_id, contact_type),
            adapter=_count_adapter,
            ttl=120,
        )

    async def _count_from_db(
        self, segment_id: uuid.UUID, contact_type: ContactMethodType
    ) -> int:
        segment = await self._segment_repo.get_by_id(segment_id)
        if segment is None:
            logger.warning("[recipient_count] segmento %s no encontrado", segment_id)
            return 0

        criteria = segment.filter_criteria
        segment_portfolio = await self._portfolio_repo.get_by_id(segment.portfolio_id)
        organization_ids = (
            [segment_portfolio.organization_id] if segment_portfolio else []
        )
        result = await self._dml.execute_query(
            tables=criteria.get("tables", []),
            joins=criteria.get("joins", []),
            limit=criteria.get("limit"),
            query_mode="detail",
            order_by=criteria.get("order_by", []),
            portfolio_ids=[segment.portfolio_id],
            organization_ids=organization_ids,
        )
        if not result.get("success"):
            logger.error(
                "[recipient_count] fallo al ejecutar segmento %s: %s",
                segment_id,
                result.get("error"),
            )
            return 0

        debtor_ids = extract_debtor_ids(json.loads(result.get("data", "[]")), criteria)
        if not debtor_ids:
            return 0

        contact_values = await self._contact_method_repo.get_all_values_by_debtors(
            debtor_ids, contact_type
        )
        # El envío usa TODOS los valores del deudor (importado +
        # autogestionado verificado) y deduplica por valor de contacto;
        # el conteo replica esa deduplicación global para no inflar el
        # número.
        unique_values = {
            value for values in contact_values.values() for value in values
        }
        return len(unique_values)
