"""Procesamiento de los eventos que Helena reporta de cada llamada.

Este servicio es **agnóstico al transporte**: recibe el cuerpo del evento ya
deserializado, no el `Request`. Hoy lo alimenta el webhook HTTP
(`helena_webhook_controller`); si algún día hubiera que cambiar a un cliente
socket.io contra Helena, solo cambia quién lo llama.

Garantías de la ingesta (los webhooks llegan desordenados y pueden repetirse,
ver `.claude/plans/ivr-helena/02-contrato-helena.md`):

- **Upsert por `interactionId`**, nunca insert ciego.
- Cada evento actualiza **solo sus campos**; no sobreescribe la fila entera.
- Un evento terminal sobre una interacción ya cerrada se registra pero **no
  vuelve a mover los agregados**.
- `handle_event` nunca propaga una excepción: el controlador debe responder
  `200` o Helena acumula fallas hasta desactivar el webhook.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.config.logger import logger
from messaging.campaigns.models.campaign_model import CampaignModel
from messaging.campaigns.repository.campaign_result_repository import (
    CampaignResultRepository,
)
from messaging.contacts.enums.contact_enums import ContactStatus
from messaging.contacts.repository.contact_repository import ContactRepository
from messaging.ivr.enums.ivr_enums import (
    CANCELLING_EVENTS,
    HELENA_STATUS_TO_EXECUTION_STATUS,
    TERMINAL_CALL_STATUSES,
    TERMINAL_EVENTS,
    TERMINAL_EXECUTION_STATUSES,
    HelenaEvent,
    IvrCallStatus,
)
from messaging.ivr.models.ivr_interaction_model import IvrInteractionModel
from messaging.ivr.repository.ivr_execution_repository import IvrExecutionRepository
from messaging.ivr.repository.ivr_flow_repository import IvrFlowRepository
from messaging.ivr.repository.ivr_interaction_repository import IvrInteractionRepository
from messaging.ivr.schemas.ivr_monitor_schemas import (
    IvrCallSchema,
    IvrCampaignStatsSchema,
)
from messaging.ivr.services.ivr_stream_emitter import (
    EVENT_CALL_UPDATED,
    EVENT_CAMPAIGN_STATUS,
    EVENT_STATS_UPDATED,
    campaign_topic,
    ivr_stream,
    organization_topic,
)
from messaging.ivr.services.outcome_resolver import resolve_outcome
from messaging.ivr.utils.interaction_mapper import (
    append_unique,
    as_int,
    as_str,
    derive_status,
    parse_helena_datetime,
)

#: Estado final de la llamada -> estado del contacto del envío.
_CALL_TO_CONTACT_STATUS: dict[IvrCallStatus, ContactStatus] = {
    IvrCallStatus.COMPLETED: ContactStatus.ANSWERED,
    IvrCallStatus.NO_ANSWER: ContactStatus.NO_ANSWER,
    IvrCallStatus.FAILED: ContactStatus.FAILED,
    IvrCallStatus.CANCELLED: ContactStatus.FAILED,
}

_CAMPAIGN_EVENTS = frozenset(
    {
        HelenaEvent.CAMPAIGN_PENDING,
        HelenaEvent.CAMPAIGN_PAUSED,
        HelenaEvent.CAMPAIGN_RESUMED,
        HelenaEvent.CAMPAIGN_CANCELLED,
        HelenaEvent.CAMPAIGN_FINISHED,
    }
)


@dataclass(frozen=True)
class BulkContext:
    """Correlación de un `bulkId` de Helena con la campaña de Pybox."""

    campaign_id: uuid.UUID | None
    organization_id: uuid.UUID | None


#: Cache de proceso `bulkId -> BulkContext`. El mapeo es inmutable una vez
#: despachado el bulk, así que no hace falta invalidarlo (mismo criterio que
#: `iris:CallMonitorProjectionService.bulkIdToCampaignId`) -- pero sí acotarlo en
#: tamaño: sin límite, un proceso de larga vida con muchas campañas IVR a lo largo
#: de meses lo haría crecer indefinidamente. Se descarta el bulkId usado hace más
#: tiempo al superar el límite (mismo criterio que `_MAX_QUEUE_SIZE` en
#: `ivr_stream_emitter`).
_BULK_CONTEXT_CACHE_MAX_SIZE = 2000
_bulk_context_cache: OrderedDict[str, BulkContext] = OrderedDict()


def _cache_bulk_context(bulk_id: str, context: BulkContext) -> None:
    _bulk_context_cache[bulk_id] = context
    _bulk_context_cache.move_to_end(bulk_id)
    if len(_bulk_context_cache) > _BULK_CONTEXT_CACHE_MAX_SIZE:
        _bulk_context_cache.popitem(last=False)


class IvrEventService:
    def __init__(
        self,
        session: AsyncSession,
        interaction_repo: IvrInteractionRepository,
        contact_repo: ContactRepository,
        result_repo: CampaignResultRepository,
        flow_repo: IvrFlowRepository,
        execution_repo: IvrExecutionRepository,
    ) -> None:
        self._session = session
        self._interactions = interaction_repo
        self._contacts = contact_repo
        self._results = result_repo
        self._flows = flow_repo
        self._executions = execution_repo

    # ── Entrada ───────────────────────────────────────────────────────────────

    async def handle_event(self, body: dict[str, Any]) -> None:
        """Procesa un evento de Helena. Nunca lanza."""
        event = as_str(body.get("event")) or ""
        if not event:
            logger.warning("[ivr_webhook] evento sin campo `event`, ignorado")
            return

        try:
            if event in _CAMPAIGN_EVENTS:
                await self._handle_campaign_event(event, body)
            elif event == HelenaEvent.TEST_EVENT:
                logger.info("[ivr_webhook] TEST_EVENT recibido correctamente")
            elif isinstance(body.get("interaction"), dict):
                await self._handle_interaction_event(event, body)
            else:
                logger.warning(
                    "[ivr_webhook] evento no procesado=%s (sin interaction)", event
                )
        except Exception:  # pylint: disable=broad-exception-caught
            # Rollback explícito: el controlador se traga el error para devolver
            # 200, y sin esto la sesión haría commit de un estado a medias.
            await self._session.rollback()
            logger.exception("[ivr_webhook] error procesando evento=%s", event)

    # ── Eventos de interacción ────────────────────────────────────────────────

    async def _handle_interaction_event(self, event: str, body: dict[str, Any]) -> None:
        interaction: dict[str, Any] = body["interaction"]
        data: dict[str, Any] = body.get("data") or {}

        interaction_id = as_str(interaction.get("interactionId"), 64)
        if not interaction_id:
            logger.warning("[ivr_webhook] evento=%s sin interactionId, ignorado", event)
            return

        bulk_id = as_str(interaction.get("bulkId"), 64)
        phone = as_str(interaction.get("phone"), 32)
        if not bulk_id or not phone:
            logger.warning(
                "[ivr_webhook] evento=%s interaction=%s sin bulkId o phone, ignorado",
                event,
                interaction_id,
            )
            return

        row = await self._interactions.get_by_interaction_id(interaction_id)
        is_new = row is None
        if row is None:
            # Los defaults de columna solo se aplican en el flush; se fijan aquí
            # para que la fila sea coherente durante todo el procesamiento del
            # evento, que ocurre antes de persistir.
            row = IvrInteractionModel(
                interaction_id=interaction_id,
                bulk_id=bulk_id,
                phone=phone,
                status=IvrCallStatus.QUEUED,
                attempt_number=1,
                transferred=False,
            )
            context = await self._resolve_bulk_context(bulk_id, phone)
            row.campaign_id = context.campaign_id
            row.organization_id = context.organization_id

        was_terminal = row.status in TERMINAL_CALL_STATUSES

        self._apply_common_fields(row, interaction)
        self._apply_event_fields(row, event, data, body)

        row.last_event = event[:60]
        row.raw_payload = body

        row.status = derive_status(
            ended_at=row.ended_at,
            dial_status=row.dial_status,
            transferred=row.transferred,
            transfer_dial_status=row.transfer_dial_status,
            transfer_started_at=row.transfer_started_at,
            amd_status=row.amd_status,
            has_ivr_activity=bool(row.dtmf_events or row.collected_data),
            cancelled=event in CANCELLING_EVENTS,
        )

        if event in TERMINAL_EVENTS:
            await self._apply_outcome(row, interaction)

        if is_new:
            await self._interactions.add(row)
        else:
            await self._interactions.update(row)

        # Los agregados y el estado del contacto solo se mueven en la primera
        # transición a terminal: un CALL_ENDED repetido no debe contar dos veces.
        if event in TERMINAL_EVENTS and not was_terminal:
            await self._propagate_to_contact(row)

        await self._emit_call_updated(row, include_stats=event in TERMINAL_EVENTS)

        logger.info(
            "[ivr_webhook] %s | interaction=%s bulk=%s estado=%s campania=%s",
            event,
            interaction_id,
            bulk_id,
            row.status,
            row.campaign_id,
        )

    def _apply_common_fields(
        self, row: IvrInteractionModel, interaction: dict[str, Any]
    ) -> None:
        """Campos que cualquier evento puede traer actualizados.

        Solo se escriben cuando el evento trae un valor: un evento posterior con
        el campo ausente no debe borrar lo que ya se sabía.
        """
        if (root := as_str(interaction.get("rootInteractionId"), 64)) is not None:
            row.root_interaction_id = root
        if (attempt := as_int(interaction.get("attemptNumber"))) is not None:
            row.attempt_number = attempt
        if (name := as_str(interaction.get("customerName"), 255)) is not None:
            row.customer_name = name
        if (doc := as_str(interaction.get("customerDocument"), 50)) is not None:
            row.customer_document = doc
        if (started := parse_helena_datetime(interaction.get("startedAt"))) is not None:
            row.started_at = started
        if (
            answered := parse_helena_datetime(interaction.get("answeredAt"))
        ) is not None:
            row.answered_at = answered
        if (
            transfer := parse_helena_datetime(interaction.get("transferStartedAt"))
        ) is not None:
            row.transfer_started_at = transfer
        if (ended := parse_helena_datetime(interaction.get("endedAt"))) is not None:
            row.ended_at = ended
        if (amd := as_str(interaction.get("amdStatus"), 20)) is not None:
            row.amd_status = amd
        if (dial := as_str(interaction.get("dialStatus"), 50)) is not None:
            row.dial_status = dial
        if (node := as_str(interaction.get("ivrEndNodeId"), 100)) is not None:
            row.ivr_end_node_id = node
        if (reason := as_str(interaction.get("ivrEndReason"), 100)) is not None:
            row.ivr_end_reason = reason
        if (duration := as_int(interaction.get("durationSeconds"))) is not None:
            row.duration_seconds = duration
        if (billable := as_int(interaction.get("billableSeconds"))) is not None:
            row.billable_seconds = billable
        if interaction.get("transferred"):
            row.transferred = True
        # `dtmfEvents` / `collectedData` llegan como el array completo acumulado
        # por Helena; se toma el más largo para no perder entradas si un evento
        # viejo llega tarde.
        if isinstance(interaction.get("dtmfEvents"), list):
            incoming = interaction["dtmfEvents"]
            if len(incoming) >= len(row.dtmf_events or []):
                row.dtmf_events = incoming
        if isinstance(interaction.get("collectedData"), list):
            incoming = interaction["collectedData"]
            if len(incoming) >= len(row.collected_data or []):
                row.collected_data = incoming

    def _apply_event_fields(
        self,
        row: IvrInteractionModel,
        event: str,
        data: dict[str, Any],
        body: dict[str, Any],
    ) -> None:
        """Campos que solo llegan en el bloque `data` de ciertos eventos.

        Varios campos de `interaction` están marcados `select: false` en
        TypeORM y no viajan en el webhook (`amdCause`, `transferDialStatus`,
        …): solo se conocen si el evento los repite aquí.
        """
        fallback_ts = parse_helena_datetime(
            (body.get("meta") or {}).get("occurredAt") or body.get("timestamp")
        )

        if event == HelenaEvent.AMD_RESULT:
            if (amd := as_str(data.get("amdStatus"), 20)) is not None:
                row.amd_status = amd
            if (cause := as_str(data.get("amdCause"), 50)) is not None:
                row.amd_cause = cause
            if row.answered_at is None:
                row.answered_at = (
                    parse_helena_datetime(data.get("answeredAt")) or fallback_ts
                )

        elif event == HelenaEvent.IVR_MENU_SELECTED:
            row.dtmf_events = append_unique(
                row.dtmf_events,
                {
                    "digit": data.get("digit"),
                    "nodeId": data.get("nodeId"),
                    "nextNode": data.get("nextNode"),
                    "after": data.get("after"),
                    "timestamp": body.get("timestamp"),
                },
            )

        elif event == HelenaEvent.IVR_COLLECT_COMPLETE:
            row.collected_data = append_unique(
                row.collected_data,
                {
                    "collected_data": data.get("value"),
                    "nodeId": data.get("nodeId"),
                    "variable": data.get("variable"),
                    "timestamp": body.get("timestamp"),
                },
            )

        elif event == HelenaEvent.IVR_TRANSFER_INITIATED:
            if row.transfer_started_at is None:
                row.transfer_started_at = (
                    parse_helena_datetime(data.get("transferStartedAt")) or fallback_ts
                )

        elif event == HelenaEvent.IVR_TRANSFER_ANSWERED:
            row.transferred = True

        elif event in (
            HelenaEvent.IVR_TRANSFER_ENDED,
            HelenaEvent.IVR_TRANSFER_NO_ANSWER,
        ):
            if (status := as_str(data.get("transferDialStatus"), 50)) is not None:
                row.transfer_dial_status = status

        elif event in TERMINAL_EVENTS and row.ended_at is None:
            # ORIGINATE_FAILED / TECHNICAL_TIMEOUT / CANCELLED pueden no traer
            # `endedAt` en la interacción; sin una fecha de cierre la llamada
            # quedaría abierta para siempre y la recogería el cron de stale.
            row.ended_at = fallback_ts or datetime.now(timezone.utc)

    # ── Tipificación del resultado ────────────────────────────────────────────

    async def _apply_outcome(
        self, row: IvrInteractionModel, interaction: dict[str, Any]
    ) -> None:
        """Traduce el desenlace técnico a la etiqueta de negocio del flujo.

        Las etiquetas se releen del flujo en cada webhook en lugar de viajar en
        el bulk: así corregir una etiqueta arregla también las llamadas que ya
        están en vuelo. El contrapeso es que editar el flujo a mitad de campaña
        cambia cómo se tipifican las llamadas restantes.
        """
        try:
            flow = await self._resolve_flow(row, interaction)
            key, label = resolve_outcome(
                ivr_end_node_id=row.ivr_end_node_id,
                ivr_end_reason=row.ivr_end_reason,
                dial_status=row.dial_status,
                amd_status=row.amd_status,
                outcomes=flow.outcomes if flow else None,
            )
            row.outcome_key = key[:100] if key else None
            row.outcome_label = label[:255] if label else None

            if label is None:
                logger.info(
                    "[ivr_webhook] sin etiqueta configurada | interaction=%s "
                    "nodo=%s clave=%s",
                    row.interaction_id,
                    row.ivr_end_node_id or "__call_level__",
                    key,
                )
        except Exception:  # pylint: disable=broad-exception-caught
            # Tipificar es informativo: si falla, la llamada igual se cierra.
            logger.exception(
                "[ivr_webhook] fallo resolviendo el resultado de %s", row.interaction_id
            )

    async def _resolve_flow(
        self, row: IvrInteractionModel, interaction: dict[str, Any]
    ):
        """Flujo IVR de la llamada: primero el id que viajó en `customFields`."""
        custom_fields = interaction.get("customFields") or {}
        raw_id = (
            as_str(custom_fields.get("ivrFlowId"))
            if isinstance(custom_fields, dict)
            else None
        )

        if raw_id is None and row.campaign_id is not None:
            # Fallback: la llamada salió antes de que se enviara el id, o el
            # bulk se despachó por fuera del motor de campañas.
            campaign = await self._campaign_flow_id(row.campaign_id)
            raw_id = str(campaign) if campaign else None

        if not raw_id:
            return None
        try:
            return await self._flows.get_by_id(uuid.UUID(raw_id))
        except ValueError:
            logger.warning("[ivr_webhook] ivrFlowId inválido=%r", raw_id)
            return None

    async def _campaign_flow_id(self, campaign_id: uuid.UUID) -> uuid.UUID | None:
        campaign = await self._session.get(CampaignModel, campaign_id)
        return campaign.ivr_flow_id if campaign else None

    # ── Correlación ───────────────────────────────────────────────────────────

    async def _resolve_bulk_context(self, bulk_id: str, phone: str) -> BulkContext:
        """Resuelve campaña y organización a partir del `bulkId`.

        El `interaction` del webhook no trae `campaignId` ni `organizationId`,
        pero `bulkId` se guardó en `contactos.id_envio` al despachar el bulk.
        """
        cached = _bulk_context_cache.get(bulk_id)
        if cached is not None:
            return cached

        contact = await self._contacts.get_by_sending_and_recipient(bulk_id, phone)
        if contact is None:
            contacts = await self._contacts.get_by_sending_id(bulk_id)
            contact = contacts[0] if contacts else None

        if contact is None:
            logger.warning(
                "[ivr_webhook] bulk=%s sin contactos en Pybox; la interacción "
                "queda sin campaña",
                bulk_id,
            )
            return BulkContext(campaign_id=None, organization_id=None)

        context = BulkContext(
            campaign_id=contact.campaign_id,
            organization_id=contact.organization_id,
        )
        _cache_bulk_context(bulk_id, context)
        return context

    async def _resolve_bulk_context_for_campaign(self, bulk_id: str) -> BulkContext:
        """Contexto de un bulk cuando el evento no trae teléfono (eventos
        CAMPAIGN_*)."""
        cached = _bulk_context_cache.get(bulk_id)
        if cached is not None:
            return cached

        contacts = await self._contacts.get_by_sending_id(bulk_id)
        if not contacts:
            return BulkContext(campaign_id=None, organization_id=None)

        context = BulkContext(
            campaign_id=contacts[0].campaign_id,
            organization_id=contacts[0].organization_id,
        )
        _cache_bulk_context(bulk_id, context)
        return context

    async def _propagate_to_contact(self, row: IvrInteractionModel) -> None:
        """Lleva el resultado final de la llamada al contacto del envío."""
        contact = await self._contacts.get_by_sending_and_recipient(
            row.bulk_id, row.phone
        )
        if contact is None:
            logger.warning(
                "[ivr_webhook] sin contacto para bulk=%s phone=%s; no se "
                "propaga el estado",
                row.bulk_id,
                row.phone,
            )
            return

        if row.contact_id is None:
            row.contact_id = contact.id
            row.debtor_id = contact.debtor_id
            await self._interactions.update(row)

        # Con remarcación gana el intento más alto ya cerrado, no el primero
        # que termine: `attemptNumber` 1 puede cerrar después que el 2 si los
        # webhooks se cruzan.
        latest = await self._interactions.get_latest_attempt_for_contact(contact.id)
        winner = (
            row
            if latest is None or row.attempt_number >= latest.attempt_number
            else latest
        )

        new_status = _CALL_TO_CONTACT_STATUS.get(winner.status)
        if new_status is None or contact.status == new_status:
            return

        contact.status = new_status
        contact.external_id = winner.interaction_id
        await self._contacts.update(contact)

    # ── Emisión en tiempo real ────────────────────────────────────────────────

    async def _emit_call_updated(
        self, row: IvrInteractionModel, include_stats: bool
    ) -> None:
        """Empuja la llamada al monitor.

        Se emite DESPUÉS de escribir en base de datos, nunca antes: lo que el
        usuario ve en vivo tiene que ser lo que quedó guardado. El commit ocurre
        al cerrar la sesión de la petición, así que en el caso extremo de que
        ese commit falle el monitor mostraría un evento que no se persistió; se
        autocorrige en el siguiente snapshot y no justifica complicar el flujo.

        Nunca propaga: un fallo emitiendo no puede tumbar la ingesta.
        """
        topics = [
            campaign_topic(row.campaign_id) if row.campaign_id else None,
            organization_topic(row.organization_id) if row.organization_id else None,
        ]
        if not any(topics):
            return

        try:
            payload = IvrCallSchema.from_model(row).model_dump(
                by_alias=True, mode="json"
            )
            await ivr_stream.emit_many(topics, EVENT_CALL_UPDATED, payload)

            if include_stats and row.campaign_id is not None:
                stats = await self._interactions.get_campaign_stats(row.campaign_id)
                await ivr_stream.emit_many(
                    topics,
                    EVENT_STATS_UPDATED,
                    IvrCampaignStatsSchema(**stats).model_dump(
                        by_alias=True, mode="json"
                    ),
                )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "[ivr_stream] fallo emitiendo la interacción %s", row.interaction_id
            )

    async def _emit_campaign_status(
        self, context: BulkContext, bulk_id: str, body: dict[str, Any]
    ) -> None:
        topics = [
            campaign_topic(context.campaign_id) if context.campaign_id else None,
            (
                organization_topic(context.organization_id)
                if context.organization_id
                else None
            ),
        ]
        if not any(topics):
            return
        try:
            await ivr_stream.emit_many(
                topics,
                EVENT_CAMPAIGN_STATUS,
                {
                    "campaignId": (
                        str(context.campaign_id) if context.campaign_id else None
                    ),
                    "bulkId": bulk_id,
                    "status": body.get("status"),
                    "quantity": body.get("quantity"),
                    "timestamp": body.get("timestamp"),
                },
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "[ivr_stream] fallo emitiendo el estado del bulk %s", bulk_id
            )

    # ── Eventos de ciclo de vida de la campaña ────────────────────────────────

    async def _handle_campaign_event(self, event: str, body: dict[str, Any]) -> None:
        bulk_id = as_str(body.get("bulkId"), 64)
        if not bulk_id:
            logger.warning("[ivr_webhook] evento=%s sin bulkId, ignorado", event)
            return

        logger.info(
            "[ivr_webhook] %s | bulk=%s campania=%s cantidad=%s",
            event,
            bulk_id,
            body.get("campaignId"),
            body.get("quantity"),
        )

        context = await self._resolve_bulk_context_for_campaign(bulk_id)
        await self._emit_campaign_status(context, bulk_id, body)
        await self._update_execution_status(bulk_id, body)

        if event != HelenaEvent.CAMPAIGN_FINISHED:
            return

        await self._record_campaign_result(bulk_id)

    async def _update_execution_status(
        self, bulk_id: str, body: dict[str, Any]
    ) -> None:
        """Refleja el `status` del payload en `ejecuciones_ivr`.

        Es la fuente de verdad final: si alguien pausa o cancela desde la
        consola de Helena en vez de Punvox, este evento igual llega y corrige
        el estado local. Sin fila que actualizar (bulk despachado antes de esta
        fase, o de una prueba suelta que no pasa por `BatchSender`), se ignora.
        """
        raw_status = as_str(body.get("status"))
        new_status = HELENA_STATUS_TO_EXECUTION_STATUS.get((raw_status or "").lower())
        if new_status is None:
            logger.warning(
                "[ivr_webhook] status de campaña desconocido=%r | bulk=%s",
                raw_status,
                bulk_id,
            )
            return

        execution = await self._executions.get_by_bulk_id(bulk_id)
        if execution is None:
            logger.debug("[ivr_webhook] sin ejecución registrada para bulk=%s", bulk_id)
            return

        if execution.status in TERMINAL_EXECUTION_STATUSES:
            # No revivir una ejecución ya cerrada por un evento desordenado.
            return

        execution.status = new_status
        if new_status in TERMINAL_EXECUTION_STATUSES and execution.finished_at is None:
            execution.finished_at = parse_helena_datetime(
                body.get("timestamp")
            ) or datetime.now(timezone.utc)
        await self._executions.update(execution)

    async def _record_campaign_result(self, bulk_id: str) -> None:
        """Inserta la fila reconciliada en `resultados_campanias`.

        Mismo rol que cumple `reconciliation_service._insert_campaign_result`
        para SMS/email: el agregado del cierre real, no el del despacho.
        """
        counts = await self._interactions.count_by_status_for_bulk(bulk_id)
        if not counts:
            logger.warning(
                "[ivr_webhook] CAMPAIGN_FINISHED bulk=%s sin interacciones", bulk_id
            )
            return

        # `organizationId` del payload es el id de la organización en Helena, no
        # el de Pybox: hay que tomarlo de nuestros propios contactos.
        context = _bulk_context_cache.get(bulk_id)
        if context is None or context.campaign_id is None:
            contacts = await self._contacts.get_by_sending_id(bulk_id)
            if not contacts:
                logger.warning(
                    "[ivr_webhook] CAMPAIGN_FINISHED bulk=%s sin contactos, "
                    "no se agrega resultado",
                    bulk_id,
                )
                return
            context = BulkContext(
                campaign_id=contacts[0].campaign_id,
                organization_id=contacts[0].organization_id,
            )

        if context.campaign_id is None or context.organization_id is None:
            logger.warning(
                "[ivr_webhook] CAMPAIGN_FINISHED bulk=%s sin campaña/"
                "organización resuelta",
                bulk_id,
            )
            return

        success = counts.get(IvrCallStatus.COMPLETED, 0)
        failure = sum(
            counts.get(status, 0)
            for status in (
                IvrCallStatus.FAILED,
                IvrCallStatus.NO_ANSWER,
                IvrCallStatus.CANCELLED,
            )
        )
        unique_customers = await self._interactions.count_unique_phones_for_bulk(
            bulk_id
        )

        # Si el bulk quedó trazado en `ejecuciones_ivr` (fase 7), se reusa su
        # `campaign_time_id`: identifica qué disparo del cron generó este envío.
        execution = await self._executions.get_by_bulk_id(bulk_id)
        campaign_time_id = execution.campaign_time_id if execution else None

        await self._results.create(
            campaign_id=context.campaign_id,
            organization_id=context.organization_id,
            campaign_time_id=campaign_time_id,
            total_sent=sum(counts.values()),
            success_count=success,
            failure_count=failure,
            unique_customers=unique_customers,
            sending_id=bulk_id,
        )

        logger.info(
            "[ivr_webhook] resultado de campaña registrado | bulk=%s "
            "exitosas=%d fallidas=%d",
            bulk_id,
            success,
            failure,
        )


def make_ivr_event_service(session: AsyncSession) -> IvrEventService:
    return IvrEventService(
        session=session,
        interaction_repo=IvrInteractionRepository(session),
        contact_repo=ContactRepository(session),
        result_repo=CampaignResultRepository(session),
        flow_repo=IvrFlowRepository(session),
        execution_repo=IvrExecutionRepository(session),
    )
