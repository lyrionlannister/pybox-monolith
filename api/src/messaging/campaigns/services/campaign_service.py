"""Alta, edición y programación de campañas de mensajería."""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status

from billing.billing_status.services.billing_status_service import BillingStatusService
from core.security.constants.permissions import PORTFOLIO_COMMUNICATIONS
from core.security.policies.security_policies import check_portfolio_org_access
from identity.users.schemas.user_session_schema import UserSession
from messaging.campaigns.constants.campaign_options import INACTIVE_WEEKDAYS
from messaging.campaigns.enums.campaign_enums import CampaignStatus, Periodicity
from messaging.campaigns.models.campaign_model import CampaignModel
from messaging.campaigns.models.campaign_time_model import CampaignTimeModel
from messaging.campaigns.repository.campaign_repository import CampaignRepository
from messaging.campaigns.repository.campaign_time_repository import (
    CampaignTimeRepository,
)
from messaging.campaigns.schemas.campaign_schemas import (
    CampaignCreateRequest,
    CampaignOccurrence,
    CampaignUpdateRequest,
)
from messaging.campaigns.services.recipient_count_service import RecipientCountService
from messaging.campaigns.utils.calculate_next import (
    calculate_next_execution,
    project_occurrences,
)
from messaging.channels.enums.channel_enums import ChannelName
from messaging.channels.repository.channel_repository import ChannelRepository
from messaging.ivr.repository.ivr_flow_repository import IvrFlowRepository
from messaging.templates.repository.template_repository import TemplateRepository
from messaging.whatsapp.services.whatsapp_number_request_service import (
    WhatsAppNumberRequestService,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.segments.repository.segment_repository import SegmentRepository
from receivables.portfolios.services.portfolio_user_access_service import (
    PortfolioUserAccessService,
)

_RECURRING = (Periodicity.DAILY, Periodicity.WEEKLY, Periodicity.MONTHLY)


class CampaignService:
    def __init__(
        self,
        campaign_repo: CampaignRepository,
        ct_repo: CampaignTimeRepository,
        billing_status_service: BillingStatusService,
        portfolio_repo: PortfolioRepository,
        template_repo: TemplateRepository,
        channel_repo: ChannelRepository,
        segment_repo: SegmentRepository,
        recipient_count_service: RecipientCountService,
        whatsapp_number_request_service: WhatsAppNumberRequestService,
        ivr_flow_repo: IvrFlowRepository,
    ) -> None:
        self._repo = campaign_repo
        self._ct_repo = ct_repo
        self._billing_status_service = billing_status_service
        self._portfolio_repo = portfolio_repo
        self._template_repo = template_repo
        self._channel_repo = channel_repo
        self._segment_repo = segment_repo
        self._recipient_count_service = recipient_count_service
        self._whatsapp_number_request_service = whatsapp_number_request_service
        self._ivr_flow_repo = ivr_flow_repo

    async def _check_portfolio_access(
        self, user_session: UserSession, portfolio_id: uuid.UUID
    ) -> uuid.UUID:
        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)
        return await check_portfolio_org_access(
            user_session,
            portfolio,
            PORTFOLIO_COMMUNICATIONS,
            check_access=PortfolioUserAccessService(
                self._portfolio_repo.session
            ).check_access,
        )

    async def list_by_org(
        self,
        portfolio_id: uuid.UUID,
        page: int,
        page_size: int,
        user_session: UserSession,
        search: str | None = None,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> tuple[list[CampaignModel], int, dict[uuid.UUID, int]]:
        """Campañas de la página, su total y los destinatarios vigentes de cada una.

        El conteo no sale de ``campanas.total_destinatarios`` (que quedó congelado en el
        valor de creación): se resuelve contra el segmento en cada lectura.
        """
        await self._check_portfolio_access(user_session, portfolio_id)
        campaigns, total = await self._repo.list_by_portfolio(
            portfolio_id, page, page_size, search, sort_by, sort_order
        )
        recipient_counts = await self._recipient_count_service.count_for_campaigns(
            campaigns
        )
        return campaigns, total, recipient_counts

    async def timeline(
        self,
        organization_id: uuid.UUID,
        range_start: datetime,
        range_end: datetime,
    ) -> list[CampaignOccurrence]:
        start = (
            range_start
            if range_start.tzinfo
            else range_start.replace(tzinfo=timezone.utc)
        )
        end = range_end if range_end.tzinfo else range_end.replace(tzinfo=timezone.utc)

        occurrences: list[CampaignOccurrence] = []
        for ct, campaign in await self._ct_repo.list_active_by_org(organization_id):
            if (
                campaign.periodicity in _RECURRING
                and ct.time_to_send
                and ct.timezone_iana
            ):
                dates = project_occurrences(
                    periodicity=campaign.periodicity.value,
                    time_to_send=ct.time_to_send,
                    timezone_iana=ct.timezone_iana,
                    range_start=start,
                    range_end=end,
                    days_of_week=ct.days_of_week,
                    day_of_month=ct.day_of_month,
                )
            else:
                dates = (
                    [ct.next_execution]
                    if ct.next_execution and start <= ct.next_execution <= end
                    else []
                )

            for occurs_at in dates:
                occurrences.append(
                    CampaignOccurrence(
                        campaign_id=campaign.id,
                        portfolio_id=campaign.portfolio_id,
                        campaign_name=campaign.name,
                        occurs_at=occurs_at,
                        periodicity=campaign.periodicity,
                        status=campaign.status,
                        is_immediate=campaign.is_immediate,
                    )
                )

        occurrences.sort(key=lambda o: o.occurs_at)
        return occurrences

    async def get_by_id(
        self, campaign_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> CampaignModel:
        await self._check_portfolio_access(user_session, portfolio_id)
        campaign = await self._repo.get_by_id_and_portfolio(campaign_id, portfolio_id)
        if campaign is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaña no encontrada")
        return campaign

    def _assert_valid_days_of_week(self, days_of_week: list[int] | None) -> None:
        if days_of_week and INACTIVE_WEEKDAYS.intersection(days_of_week):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "No se pueden programar campañas el domingo",
            )

    def _assert_valid_day_of_month(self, day_of_month: int | None) -> None:
        # 31 actúa como "último día del mes": calculate_next_execution
        # clampea siempre min(day_of_month, último_día_real_del_mes), así
        # que 31 resuelve a 28/29/30/31 según el mes.
        if day_of_month is not None and not 1 <= day_of_month <= 31:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "El día del mes debe estar entre 1 y 31",
            )

    def _validate_scheduling_input(
        self,
        is_immediate: bool,
        periodicity: Periodicity | None,
        scheduled_at: datetime | None,
        time_to_send: str | None,
        days_of_week: list[int] | None,
    ) -> None:
        if is_immediate:
            return

        if periodicity == Periodicity.ONCE:
            if not scheduled_at or not time_to_send:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Para periodicity='UNA_VEZ' se requiere scheduled_at "
                    "y time_to_send",
                )
            return

        if periodicity in (Periodicity.DAILY, Periodicity.WEEKLY, Periodicity.MONTHLY):
            if not time_to_send:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Para periodicity='{periodicity.value}' se requiere time_to_send",
                )
            if periodicity == Periodicity.WEEKLY and not days_of_week:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Para periodicity='SEMANAL' se requiere al menos un "
                    "día en days_of_week",
                )

    async def assert_template_channel_compatibility(
        self, template_id: uuid.UUID, channel_id: uuid.UUID, portfolio_id: uuid.UUID
    ) -> None:
        template = await self._template_repo.get_by_id_and_portfolio(
            template_id, portfolio_id
        )
        if template is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"No existe la plantilla {template_id}"
            )

        channel = await self._channel_repo.get_by_id(channel_id)
        if channel is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"No existe el canal {channel_id}"
            )

        if template.channel != channel.name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"La plantilla {template_id} no pertenece al canal "
                f"{channel.name.value}",
            )

    async def _validate_channel_content(
        self, channel_id: uuid.UUID, template_id: uuid.UUID | None, message: str | None
    ) -> None:
        channel = await self._channel_repo.get_by_id(channel_id)
        if channel is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"No existe el canal {channel_id}"
            )

        if channel.name == ChannelName.WHATSAPP:
            if template_id is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Las campañas de WhatsApp requieren 'templateId' (el "
                    "contenido vive en la plantilla de Meta)",
                )
            if message:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "El campo 'message' no aplica para campañas de WhatsApp",
                )
        elif channel.name != ChannelName.CALL and not message:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "El campo 'message' es obligatorio para este canal",
            )

    async def _assert_ivr_flow_for_channel(
        self,
        channel_id: uuid.UUID,
        ivr_flow_id: uuid.UUID | None,
        portfolio_id: uuid.UUID,
    ) -> None:
        """El canal de llamadas (CALL) exige un flujo IVR válido del
        mismo portafolio."""
        channel = await self._channel_repo.get_by_id(channel_id)
        if channel is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"No existe el canal {channel_id}"
            )
        if channel.name != ChannelName.CALL:
            return
        if ivr_flow_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "El canal de llamadas requiere un flujo IVR (ivr_flow_id)",
            )
        flow = await self._ivr_flow_repo.get_by_id_and_portfolio(
            ivr_flow_id, portfolio_id
        )
        if flow is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"No existe el flujo IVR {ivr_flow_id} en este portafolio",
            )

    async def _assert_segment_in_portfolio(
        self, segment_id: uuid.UUID, portfolio_id: uuid.UUID
    ) -> None:
        segment = await self._segment_repo.get_by_id_and_portfolio(
            segment_id, portfolio_id
        )
        if segment is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"No existe el segmento {segment_id} en este portafolio",
            )

    async def create(
        self,
        portfolio_id: uuid.UUID,
        data: CampaignCreateRequest,
        user_session: UserSession,
    ) -> CampaignModel:
        organization_id = await self._check_portfolio_access(user_session, portfolio_id)
        self._assert_valid_days_of_week(data.days_of_week)
        self._assert_valid_day_of_month(data.day_of_month)
        self._validate_scheduling_input(
            data.is_immediate,
            data.periodicity,
            data.scheduled_at,
            data.time_to_send,
            data.days_of_week,
        )
        if data.template_id is not None:
            await self.assert_template_channel_compatibility(
                data.template_id, data.channel_id, portfolio_id
            )
        if data.segment_id is not None:
            await self._assert_segment_in_portfolio(data.segment_id, portfolio_id)
        await self._validate_channel_content(
            data.channel_id, data.template_id, data.message
        )
        await self._assert_ivr_flow_for_channel(
            data.channel_id, data.ivr_flow_id, portfolio_id
        )

        channel = await self._channel_repo.get_by_id(data.channel_id)
        if channel is not None and channel.name == ChannelName.WHATSAPP:
            # No bloquea: la campaña se puede armar en borrador mientras el equipo de
            # soporte provisiona el número (ticket automático, ver activate()).
            await self._whatsapp_number_request_service.ensure_number_available(
                organization_id, user_session.user_id
            )

        campaign = CampaignModel(
            portfolio_id=portfolio_id,
            name=data.name,
            message=data.message,
            subject=data.subject,
            channel_id=data.channel_id,
            description=data.description,
            status=data.status,
            total_recipients=data.total_recipients,
            scheduled_at=data.scheduled_at,
            timezone=data.timezone,
            fallback=data.fallback,
            segment_id=data.segment_id,
            template_id=data.template_id,
            periodicity=data.periodicity,
            time_to_send=data.time_to_send,
            is_immediate=data.is_immediate,
            days_of_week=data.days_of_week,
            day_of_month=data.day_of_month,
            ivr_flow_id=data.ivr_flow_id,
        )
        return await self._repo.add(campaign)

    async def update(
        self,
        campaign_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        data: CampaignUpdateRequest,
        user_session: UserSession,
    ) -> CampaignModel:
        organization_id = await self._check_portfolio_access(user_session, portfolio_id)
        campaign = await self._repo.get_by_id_and_portfolio(campaign_id, portfolio_id)
        if campaign is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaña no encontrada")
        self._assert_valid_days_of_week(data.days_of_week)
        self._assert_valid_day_of_month(data.day_of_month)

        template_id = (
            data.template_id if data.template_id is not None else campaign.template_id
        )
        channel_id = (
            data.channel_id if data.channel_id is not None else campaign.channel_id
        )
        if template_id is not None and (
            data.template_id is not None or data.channel_id is not None
        ):
            await self.assert_template_channel_compatibility(
                template_id, channel_id, portfolio_id
            )
        if data.segment_id is not None:
            await self._assert_segment_in_portfolio(data.segment_id, portfolio_id)
        if (
            data.message is not None
            or data.channel_id is not None
            or data.template_id is not None
        ):
            effective_message = (
                data.message if data.message is not None else campaign.message
            )
            await self._validate_channel_content(
                channel_id, template_id, effective_message
            )
        if data.channel_id is not None or data.ivr_flow_id is not None:
            ivr_flow_id = (
                data.ivr_flow_id
                if data.ivr_flow_id is not None
                else campaign.ivr_flow_id
            )
            await self._assert_ivr_flow_for_channel(
                channel_id, ivr_flow_id, portfolio_id
            )

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(campaign, key, value)
        # Si la campaña ya está programada, re-sincronizar su programación para
        # que la línea de tiempo refleje los nuevos parámetros de envío.
        if campaign.status == CampaignStatus.SCHEDULED:
            await self._sync_schedule(campaign, organization_id)
        return await self._repo.update(campaign)

    async def delete(
        self, campaign_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> None:
        campaign = await self.get_by_id(campaign_id, portfolio_id, user_session)
        await self._repo.delete(campaign)

    async def restore(self, campaign_id: uuid.UUID) -> CampaignModel:
        """Solo Admin Global: no exige portfolio_id ni valida tenant-scope, el llamador
        ya lo autorizó a nivel de policy antes de llegar acá."""
        campaign = await self._repo.get_by_id_including_deleted(campaign_id)
        if campaign is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaña no encontrada")
        return await self._repo.restore(campaign)

    async def activate(
        self, campaign_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> CampaignModel:
        organization_id = await self._check_portfolio_access(user_session, portfolio_id)

        if await self._billing_status_service.is_blocked(organization_id):
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                "Envíos bloqueados por factura vencida sin pagar. Realiza "
                "el pago para reanudarlos.",
            )

        campaign = await self._repo.get_by_id_and_portfolio(campaign_id, portfolio_id)
        if campaign is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaña no encontrada")

        if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Solo campañas en borrador o pausadas pueden activarse",
            )

        if not campaign.segment_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "La campaña debe tener un segmento asignado",
            )

        channel = await self._channel_repo.get_by_id(campaign.channel_id)
        if channel is not None and channel.name == ChannelName.WHATSAPP:
            has_number = (
                await self._whatsapp_number_request_service.ensure_number_available(
                    organization_id, user_session.user_id
                )
            )
            if not has_number:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Esta organización todavía no tiene un número de "
                    "WhatsApp configurado. Se generó una solicitud a "
                    "soporte; la campaña se puede activar cuando quede "
                    "lista.",
                )

        await self._sync_schedule(campaign, organization_id)

        campaign.status = CampaignStatus.SCHEDULED
        return await self._repo.update(campaign)

    async def _sync_schedule(
        self, campaign: CampaignModel, organization_id: uuid.UUID
    ) -> None:
        """Calcula la próxima ejecución y crea/actualiza el CampaignTimeModel activo
        a partir de los parámetros de envío actuales de la campaña."""
        now = datetime.now(timezone.utc)
        next_execution: datetime

        if campaign.is_immediate:
            next_execution = now
        elif campaign.periodicity == Periodicity.ONCE and campaign.scheduled_at:
            next_execution = campaign.scheduled_at
        elif campaign.periodicity in _RECURRING:
            if not campaign.time_to_send:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Campaña recurrente requiere time_to_send",
                )
            next_execution = calculate_next_execution(
                periodicity=campaign.periodicity.value,
                time_to_send=campaign.time_to_send,
                timezone_iana=campaign.timezone,
                days_of_week=campaign.days_of_week,
                day_of_month=campaign.day_of_month,
                from_dt=now,
            )
        else:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Periodicidad no válida para activación",
            )

        existing_ct = await self._ct_repo.get_by_campaign(campaign.id)
        if existing_ct:
            existing_ct.is_active = True
            existing_ct.next_execution = next_execution
            existing_ct.timezone_iana = campaign.timezone
            existing_ct.is_immediate = campaign.is_immediate
            existing_ct.time_to_send = campaign.time_to_send
            existing_ct.days_of_week = campaign.days_of_week
            existing_ct.day_of_month = campaign.day_of_month
            await self._ct_repo.update(existing_ct)
        else:
            ct = CampaignTimeModel(
                campaign_id=campaign.id,
                organization_id=organization_id,
                next_execution=next_execution,
                timezone_iana=campaign.timezone,
                is_active=True,
                is_immediate=campaign.is_immediate,
                time_to_send=campaign.time_to_send,
                days_of_week=campaign.days_of_week,
                day_of_month=campaign.day_of_month,
            )
            await self._ct_repo.add(ct)

    async def pause(
        self, campaign_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> CampaignModel:
        campaign = await self.get_by_id(campaign_id, portfolio_id, user_session)
        if campaign.status != CampaignStatus.SCHEDULED:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Solo campañas programadas pueden pausarse"
            )
        ct = await self._ct_repo.get_by_campaign(campaign_id)
        if ct:
            await self._ct_repo.deactivate(ct)
        campaign.status = CampaignStatus.PAUSED
        return await self._repo.update(campaign)
