"""Motor de automatización de campañas: procesa las programaciones vencidas."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.repository.country_repository import CountryRepository
from app_platform.schema_manager.services.dml_service import DmlService
from app_platform.schema_manager.services.inspector_service import InspectorService
from billing.billing_status.services.billing_status_service import BillingStatusService
from billing.invoices.repository.invoice_repository import InvoiceRepository
from core.config.logger import logger
from core.database.database import db
from core.security.services.encrypt_service import encrypt_service
from messaging.campaigns.constants.channel_contact_constants import CHANNEL_CONTACT_TYPE
from messaging.campaigns.enums.campaign_enums import CampaignStatus, Periodicity
from messaging.campaigns.models.campaign_model import CampaignModel
from messaging.campaigns.models.campaign_time_model import CampaignTimeModel
from messaging.campaigns.repository.campaign_repository import CampaignRepository
from messaging.campaigns.repository.campaign_result_repository import (
    CampaignResultRepository,
)
from messaging.campaigns.repository.campaign_time_repository import (
    CampaignTimeRepository,
)
from messaging.campaigns.schemas.batch_schemas import BatchStats, SendInput
from messaging.campaigns.services.batch_sender import BatchSender
from messaging.campaigns.services.personalization_service import PersonalizationService
from messaging.campaigns.utils.calculate_next import calculate_next_execution
from messaging.campaigns.utils.provider_utils import normalize_phone
from messaging.campaigns.utils.segment_utils import debtor_id_column, extract_debtor_ids
from messaging.campaigns.utils.substitution_utils import build_sub
from messaging.channels.enums.channel_enums import ChannelName
from messaging.channels.repository.channel_repository import ChannelRepository
from messaging.contacts.repository.contact_repository import ContactRepository
from messaging.dispatcher import MessageDispatcher
from messaging.ivr.repository.ivr_execution_repository import IvrExecutionRepository
from messaging.ivr.repository.ivr_flow_repository import IvrFlowRepository
from messaging.provider_credentials.services.provider_credential_service import (
    MessagingProviderCredentialService,
)
from messaging.templates.services.template_renderer import TemplateRenderer
from messaging.templates.services.template_variable_service import (
    TemplateVariableService,
)
from messaging.whatsapp.enums.whatsapp_enums import ChannelRequestStatus
from messaging.whatsapp.models.whatsapp_template_data_model import (
    WhatsAppTemplateDataModel,
)
from messaging.whatsapp.repository.whatsapp_channel_request_repository import (
    WhatsAppChannelRequestRepository,
)
from messaging.whatsapp.repository.whatsapp_org_credentials_repository import (
    WhatsAppOrgCredentialsRepository,
)
from messaging.whatsapp.repository.whatsapp_template_data_repository import (
    WhatsAppTemplateDataRepository,
)
from messaging.whatsapp.services.whatsapp_channel_request_service import (
    WhatsAppChannelRequestService,
)
from messaging.whatsapp.services.whatsapp_client import WhatsAppCloudClient
from messaging.whatsapp.utils.whatsapp_template_parser import extract_variable_slots
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType
from receivables.contact_methods.repository.contact_method_repository import (
    ContactMethodRepository,
)
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.segments.repository.segment_repository import SegmentRepository

_DISPATCHER = MessageDispatcher()

# Cada campaña se procesa en su propia sesión (=conexión). El pool async
# por defecto es 5 + 10 overflow = 15 conexiones compartidas con la API,
# así que se limita la concurrencia muy por debajo para no agotarlo; el
# resto de campañas esperan en el semáforo.
_MAX_CONCURRENT = 5
_sem = asyncio.Semaphore(_MAX_CONCURRENT)
_executing: set[uuid.UUID] = set()


def is_executing(campaign_id: uuid.UUID) -> bool:
    return campaign_id in _executing


def make_automation_service(session: AsyncSession) -> AutomationService:
    debtor_repo = DebtorRepository(session)
    return AutomationService(
        session=session,
        campaign_repo=CampaignRepository(session),
        ct_repo=CampaignTimeRepository(session),
        result_repo=CampaignResultRepository(session),
        channel_repo=ChannelRepository(session),
        ivr_flow_repo=IvrFlowRepository(session),
        seg_repo=SegmentRepository(session),
        dml=DmlService(session),
        batch_sender=BatchSender(
            _DISPATCHER, ContactRepository(session), IvrExecutionRepository(session)
        ),
        billing_status_service=BillingStatusService(InvoiceRepository(session)),
        template_var_service=TemplateVariableService(InspectorService(session)),
        personalization=PersonalizationService(
            debtor_repo, CreditRepository(session), PaymentRepository(session)
        ),
        contact_method_repo=ContactMethodRepository(session),
        debtor_repo=debtor_repo,
        portfolio_repo=PortfolioRepository(session),
        whatsapp_credentials_repo=WhatsAppOrgCredentialsRepository(session),
        whatsapp_template_data_repo=WhatsAppTemplateDataRepository(session),
        whatsapp_channel_request_service=WhatsAppChannelRequestService(
            WhatsAppChannelRequestRepository(session)
        ),
        whatsapp_client=WhatsAppCloudClient(),
    )


class AutomationService:
    def __init__(
        self,
        session: AsyncSession,
        campaign_repo: CampaignRepository,
        ct_repo: CampaignTimeRepository,
        result_repo: CampaignResultRepository,
        channel_repo: ChannelRepository,
        ivr_flow_repo: IvrFlowRepository,
        seg_repo: SegmentRepository,
        dml: DmlService,
        batch_sender: BatchSender,
        billing_status_service: BillingStatusService,
        template_var_service: TemplateVariableService,
        personalization: PersonalizationService,
        contact_method_repo: ContactMethodRepository,
        debtor_repo: DebtorRepository,
        portfolio_repo: PortfolioRepository,
        whatsapp_credentials_repo: WhatsAppOrgCredentialsRepository,
        whatsapp_template_data_repo: WhatsAppTemplateDataRepository,
        whatsapp_channel_request_service: WhatsAppChannelRequestService,
        whatsapp_client: WhatsAppCloudClient,
    ) -> None:
        self._session = session
        self._campaign_repo = campaign_repo
        self._ct_repo = ct_repo
        self._result_repo = result_repo
        self._channel_repo = channel_repo
        self._ivr_flow_repo = ivr_flow_repo
        self._seg_repo = seg_repo
        self._dml = dml
        self._batch_sender = batch_sender
        self._billing_status_service = billing_status_service
        self._template_var_service = template_var_service
        self._personalization = personalization
        self._contact_method_repo = contact_method_repo
        self._debtor_repo = debtor_repo
        self._portfolio_repo = portfolio_repo
        self._country_repo = CountryRepository(portfolio_repo.session)
        self._credential_service = MessagingProviderCredentialService(
            portfolio_repo.session
        )
        self._whatsapp_credentials_repo = whatsapp_credentials_repo
        self._whatsapp_template_data_repo = whatsapp_template_data_repo
        self._whatsapp_channel_request_service = whatsapp_channel_request_service
        self._whatsapp_client = whatsapp_client

    async def tick(self) -> int:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

        processed = 0
        batch_size = 300
        after_id: uuid.UUID | None = None

        while True:
            due = await self._ct_repo.find_due_active(now, batch_size, after_id)
            if not due:
                break

            after_id = due[-1].id

            # Se capturan los ids antes de procesar: cada campaña corre
            # en su PROPIA sesión, de modo que un fallo (p. ej. un INSERT
            # inválido) no contamine a las demás ni a la sesión de
            # lectura de este tick. Loguear con ids capturados evita
            # recargar atributos ORM sobre una sesión potencialmente rota.
            due_refs = [(ct.id, ct.campaign_id) for ct in due]
            tasks = [self._guarded_process(ct_id, now) for ct_id, _ in due_refs]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (ct_id, campaign_id), result in zip(due_refs, results):
                if isinstance(result, Exception):
                    logger.error(
                        "[automation] error campaña=%s (programacion=%s): %s",
                        campaign_id,
                        ct_id,
                        result,
                    )
                elif result:
                    processed += 1

            if len(due) < batch_size:
                break

        return processed

    async def _guarded_process(self, ct_id: uuid.UUID, now: datetime) -> bool:
        async with _sem:
            async with db.get_session() as session:
                # `svc` es otra instancia de esta misma clase (con su propia
                # sesión) — acceso legítimo a sus miembros "privados", no una
                # fuga de encapsulación hacia afuera de AutomationService.
                svc = make_automation_service(session)
                # pylint: disable=protected-access
                ct = await svc._ct_repo.get_by_id(ct_id)
                if ct is None:
                    return False
                if ct.campaign_id in _executing:
                    logger.debug(
                        "[automation] campaña %s ya en ejecución, omitida",
                        ct.campaign_id,
                    )
                    return False
                _executing.add(ct.campaign_id)
                try:
                    return await svc._process_due(ct, now)
                finally:
                    _executing.discard(ct.campaign_id)
                # pylint: enable=protected-access

    async def _process_due(self, ct: CampaignTimeModel, now: datetime) -> bool:
        campaign = await self._campaign_repo.get_by_id(ct.campaign_id)
        if campaign is None:
            return False

        if await self._billing_status_service.is_blocked(ct.organization_id):
            logger.warning(
                "[automation] organización %s bloqueada por facturación, "
                "envío de campaña %s omitido",
                ct.organization_id,
                campaign.id,
            )
            # No se desactiva ni reprograma: se reintenta en el siguiente
            # tick hasta que se desbloquee.
            return False

        # El envío es best-effort: si falla, se registra pero NO se aborta
        # la reprogramación, para que la campaña no quede atascada
        # venciendo indefinidamente.
        try:
            await self._execute_campaign_once(campaign, ct)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "[automation] campaña %s: fallo en el envío; se reprograma igual",
                campaign.id,
            )

        periodicity = campaign.periodicity

        if campaign.is_immediate or periodicity in (None, Periodicity.ONCE):
            await self._ct_repo.deactivate(ct)
            await self._set_campaign_status(campaign, CampaignStatus.COMPLETED)
            logger.info(
                "[automation] campaña %s completada (once/immediate)", campaign.id
            )
            return True

        if not campaign.time_to_send or not ct.timezone_iana:
            logger.error(
                "[automation] campaña %s sin time_to_send o timezone", campaign.id
            )
            return True

        try:
            next_dt = calculate_next_execution(
                periodicity=periodicity.value,
                time_to_send=campaign.time_to_send,
                timezone_iana=ct.timezone_iana,
                days_of_week=ct.days_of_week,
                day_of_month=ct.day_of_month,
                from_dt=now,
            )
            await self._ct_repo.reschedule(ct, next_dt)
            logger.info(
                "[automation] campaña %s reprogramada para %s", campaign.id, next_dt
            )
        except ValueError as exc:
            logger.error(
                "[automation] campaña %s error recalculando: %s", campaign.id, exc
            )

        return True

    async def _execute_campaign_once(
        self, campaign: CampaignModel, ct: CampaignTimeModel
    ) -> None:
        if not campaign.segment_id:
            logger.warning(
                "[automation] campaña %s sin segment_id, omitida", campaign.id
            )
            return

        segment = await self._seg_repo.get_by_id(campaign.segment_id)
        if segment is None:
            logger.error("[automation] segmento %s no encontrado", campaign.segment_id)
            return

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
                "[automation] campaña %s: fallo al ejecutar segmento: %s",
                campaign.id,
                result.get("error"),
            )
            return

        rows: list[dict] = json.loads(result.get("data", "[]"))
        if not rows:
            logger.warning(
                "[automation] campaña %s: segmento sin destinatarios", campaign.id
            )
            return

        logger.info(
            "[automation] campaña %s: %d filas del segmento", campaign.id, len(rows)
        )

        channel_model = await self._channel_repo.get_by_id(campaign.channel_id)
        if channel_model is None:
            logger.error(
                "[automation] campaña %s: canal %s no encontrado",
                campaign.id,
                campaign.channel_id,
            )
            return
        snapshot_channel_id = channel_model.id
        snapshot_currency = channel_model.currency
        snapshot_unit_price = channel_model.unit_price

        contact_type = CHANNEL_CONTACT_TYPE.get(channel_model.name)
        if contact_type is None:
            logger.error(
                "[automation] campaña %s: canal %s sin tipo de contacto asociado",
                campaign.id,
                channel_model.name,
            )
            return

        # Canal de llamadas IVR: resolver el flujo configurado y armar el contexto
        # que el BatchSender entregará al canal para el envío bulk a Helena.
        channel_context: dict[str, Any] | None = None
        if channel_model.name == ChannelName.CALL:
            if not campaign.ivr_flow_id:
                logger.error(
                    "[automation] campaña %s (IVR) sin ivr_flow_id, omitida",
                    campaign.id,
                )
                return
            ivr_flow = await self._ivr_flow_repo.get_by_id(campaign.ivr_flow_id)
            if ivr_flow is None or not ivr_flow.config:
                logger.error(
                    "[automation] campaña %s: flujo IVR %s no encontrado o sin config",
                    campaign.id,
                    campaign.ivr_flow_id,
                )
                return
            channel_context = {
                "ivr_config": ivr_flow.config,
                "redial_config": ivr_flow.redial_config,
                "variables": ivr_flow.variables,
                "campaign_id": str(campaign.id),
                "ivr_flow_id": str(ivr_flow.id),
                "campaign_time_id": str(ct.id),
                "caller_id": ivr_flow.caller_id,
                "calls_per_second": ivr_flow.calls_per_second,
                "max_concurrent": ivr_flow.max_concurrent,
                "contact_policy_id": ivr_flow.contact_policy_id,
            }

        is_whatsapp = channel_model.name == ChannelName.WHATSAPP
        content = campaign.message
        language: str | None = None
        phone_number_id: str | None = None
        if is_whatsapp:
            credentials = await self._whatsapp_credentials_repo.get_by_organization(
                ct.organization_id
            )
            if credentials is None or not credentials.active:
                logger.error(
                    "[automation] campaña %s: organización sin número de "
                    "WhatsApp configurado",
                    campaign.id,
                )
                return
            phone_number_id = credentials.phone_number_id

            if campaign.template_id is None:
                logger.error(
                    "[automation] campaña %s: WhatsApp requiere una plantilla",
                    campaign.id,
                )
                return
            whatsapp_data = await self._whatsapp_template_data_repo.get_by_template_id(
                campaign.template_id
            )
            if whatsapp_data is None:
                logger.error(
                    "[automation] campaña %s: plantilla de WhatsApp no encontrada",
                    campaign.id,
                )
                return
            content = whatsapp_data.meta_name
            language = whatsapp_data.language

        # El segmento solo identifica a los deudores; el valor de contacto
        # se resuelve aquí, en ejecución, según el canal (SMS/WhatsApp/
        # llamada → teléfono, correo → email).
        debtor_ids = extract_debtor_ids(rows, criteria)
        if not debtor_ids:
            logger.warning(
                "[automation] campaña %s: segmento sin deudores "
                "identificables (columna=%s)",
                campaign.id,
                debtor_id_column(criteria),
            )
            return

        contact_values = await self._contact_method_repo.get_all_values_by_debtors(
            debtor_ids, contact_type
        )
        # El documento se guarda cifrado en ``deudores``;
        # ``contactos.documento_deudor`` es texto plano (VARCHAR(50)),
        # así que se descifra antes de persistir.
        documents = {
            d.id: self._safe_decrypt_document(d.document_number)
            for d in await self._debtor_repo.get_by_ids(debtor_ids)
        }

        phone_prefix = None
        if contact_type == ContactMethodType.PHONE:
            phone_prefix = await self._resolve_phone_prefix(
                campaign.portfolio_id, campaign.id
            )

        recipients: list[tuple[str, uuid.UUID, str | None]] = []
        unique_recipients: set[str] = set()
        pending_approval = 0

        # Prefetch en batch del estado de consentimiento de todos los teléfonos del
        # segmento: evita un SELECT de "ensure_case" por destinatario en cada corrida
        # (esto se ejecuta en un cron periódico, no es un evento único).
        case_status_cache: dict[str, ChannelRequestStatus] = {}
        if is_whatsapp:
            all_phones = list(
                {
                    (
                        normalize_phone(recipient, phone_prefix)
                        if phone_prefix
                        else recipient
                    )
                    for debtor_id in debtor_ids
                    for recipient in contact_values.get(debtor_id, [])
                    if recipient
                }
            )
            case_status_cache = (
                await self._whatsapp_channel_request_service.get_existing_statuses(
                    ct.organization_id, all_phones
                )
            )

            # Teléfonos sin caso previo: se crean TODOS de una vez en vez de un
            # ensure_case (SELECT+INSERT) por destinatario dentro del loop de abajo.
            # "Primer deudor que trae el teléfono" decide el debtor_id del caso,
            # igual que el orden en que el loop los habría ido creando.
            missing_phone_to_debtor_id: dict[str, uuid.UUID | None] = {}
            for debtor_id in debtor_ids:
                for recipient in contact_values.get(debtor_id, []):
                    if not recipient:
                        continue
                    phone = (
                        normalize_phone(recipient, phone_prefix)
                        if phone_prefix
                        else recipient
                    )
                    if (
                        phone not in case_status_cache
                        and phone not in missing_phone_to_debtor_id
                    ):
                        missing_phone_to_debtor_id[phone] = debtor_id
            if missing_phone_to_debtor_id:
                await self._whatsapp_channel_request_service.ensure_cases_bulk(
                    ct.organization_id,
                    missing_phone_to_debtor_id,
                    origin_campaign_id=campaign.id,
                )
                for phone in missing_phone_to_debtor_id:
                    case_status_cache[phone] = ChannelRequestStatus.PENDING

        # Un deudor puede tener varios valores del mismo tipo (importado por la org +
        # autogestionado verificado por el titular): se contactan todos.
        for debtor_id in debtor_ids:
            for recipient in contact_values.get(debtor_id, []):
                if not recipient or recipient in unique_recipients:
                    continue

                if is_whatsapp:
                    phone = (
                        normalize_phone(recipient, phone_prefix)
                        if phone_prefix
                        else recipient
                    )
                    case_status = case_status_cache.get(
                        phone, ChannelRequestStatus.PENDING
                    )
                    if case_status != ChannelRequestStatus.APPROVED:
                        pending_approval += 1
                        continue

                unique_recipients.add(recipient)
                recipients.append((recipient, debtor_id, documents.get(debtor_id)))

        if pending_approval:
            logger.info(
                "[automation] campaña %s: %d destinatarios en espera de "
                "aprobación de canal WhatsApp",
                campaign.id,
                pending_approval,
            )

        # Para WhatsApp no hay {var} en campaign.message (el contenido vive en la
        # plantilla de Meta) — las variables nombradas se leen en vivo del body
        # aprobado y se resuelven contra deudores/creditos igual que SMS/Email.
        debtor_ids_to_personalize = [debtor_id for _, debtor_id, _ in recipients]
        personalization_data = (
            await self._resolve_whatsapp_personalization(
                whatsapp_data, debtor_ids_to_personalize
            )
            if is_whatsapp
            else await self._resolve_personalization(
                campaign, debtor_ids_to_personalize
            )
        )

        send_inputs: list[SendInput] = [
            SendInput(
                recipient=recipient,
                content=content,
                subject=None if is_whatsapp else campaign.subject,
                debtor_id=debtor_id,
                debtor_document=debtor_document,
                campaign_id=campaign.id,
                organization_id=ct.organization_id,
                portfolio_id=campaign.portfolio_id,
                snapshot_channel_id=snapshot_channel_id,
                snapshot_currency=snapshot_currency,
                snapshot_unit_price=snapshot_unit_price,
                sub=(
                    build_sub(personalization_data.get(debtor_id))
                    if debtor_id
                    else None
                ),
            )
            for recipient, debtor_id, debtor_document in recipients
        ]

        if not send_inputs:
            logger.warning(
                "[automation] campaña %s: 0 destinatarios con %s válido",
                campaign.id,
                contact_type.value,
            )
            return

        batch_portfolio = await self._portfolio_repo.get_by_id(campaign.portfolio_id)
        stats: BatchStats = await self._batch_sender.process_batch(
            send_inputs,
            channel_model.name,
            phone_prefix=phone_prefix,
            campaign_name=campaign.name,
            phone_number_id=phone_number_id,
            language=language,
            credential_service=self._credential_service,
            country=batch_portfolio.country if batch_portfolio else None,
            channel_context=channel_context,
        )

        # Registro de resultado en un savepoint: si falla no debe
        # envenenar la transacción de la campaña (la reprogramación
        # posterior tiene que poder confirmarse).
        try:
            async with self._session.begin_nested():
                await self._result_repo.create(
                    campaign_id=campaign.id,
                    organization_id=ct.organization_id,
                    campaign_time_id=ct.id,
                    total_sent=stats.total_sent,
                    success_count=stats.success_count,
                    failure_count=stats.failure_count,
                    unique_customers=stats.unique_customers,
                )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "[automation] campaña %s: no se pudo registrar el resultado",
                campaign.id,
            )

        logger.info(
            "[automation] campaña %s: %d/%d exitosos, %d únicos",
            campaign.id,
            stats.success_count,
            stats.total_sent,
            stats.unique_customers,
        )

    @staticmethod
    def _safe_decrypt_document(encrypted: str | None) -> str | None:
        if not encrypted:
            return None
        try:
            return encrypt_service.decrypt_to_str(encrypted)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning("[automation] no se pudo descifrar el documento del deudor")
            return None

    async def _resolve_phone_prefix(
        self, portfolio_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> str | None:
        """Indicativo telefónico según el país del portafolio (``None``
        si no está definido)."""
        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)
        country = portfolio.country if portfolio else None
        prefix = await self._country_repo.get_phone_prefix(country)
        if prefix is None:
            logger.warning(
                "[automation] campaña %s: portafolio %s sin país/"
                "indicativo; se envía sin prefijo",
                campaign_id,
                portfolio_id,
            )
        return prefix

    async def _resolve_personalization(
        self, campaign: CampaignModel, debtor_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, Any]]:
        renderer = TemplateRenderer()
        placeholders = renderer.find_variables(campaign.message)
        if campaign.subject:
            placeholders |= renderer.find_variables(campaign.subject)
        return await self._fetch_personalization(placeholders, debtor_ids)

    async def _resolve_whatsapp_personalization(
        self,
        whatsapp_data: WhatsAppTemplateDataModel | None,
        debtor_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, dict[str, Any]]:
        if whatsapp_data is None or whatsapp_data.meta_template_id is None:
            return {}
        # Sin caché local del body: se consulta la plantilla aprobada en vivo para
        # saber qué variables nombradas necesita este envío.
        template = await self._whatsapp_client.get_template(
            whatsapp_data.meta_template_id
        )
        slots = extract_variable_slots(template.get("components", []))
        placeholders = {slot.name for slot in slots}
        return await self._fetch_personalization(placeholders, debtor_ids)

    async def _fetch_personalization(
        self, placeholders: set[str], debtor_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, Any]]:
        if not placeholders or not debtor_ids:
            return {}

        variables = await self._template_var_service.list_available_variables()
        field_table = {v.key: v.source_table for v in variables}

        fields_by_table: dict[str, set[str]] = {}
        for field in placeholders:
            table = field_table.get(field)
            if table:
                fields_by_table.setdefault(table, set()).add(field)

        if not fields_by_table:
            return {}

        return await self._personalization.fetch(list(set(debtor_ids)), fields_by_table)

    async def _set_campaign_status(
        self, campaign: CampaignModel, status: CampaignStatus
    ) -> None:
        campaign.status = status
        await self._campaign_repo.update(campaign)
