"""Envío por lotes de una campaña, con reintentos y agregación de estadísticas."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from core.config.logger import logger
from messaging.campaigns.constants import BATCH_SIZE, MAX_RETRIES, RETRY_BASE_MS
from messaging.campaigns.schemas.batch_schemas import BatchStats, SendInput
from messaging.campaigns.utils.provider_utils import (
    is_phone_channel,
    normalize_phone,
    provider_for_channel,
)
from messaging.contacts.enums.contact_enums import ContactStatus, ProviderType
from messaging.contacts.models.contact_model import ContactModel
from messaging.contacts.repository.contact_repository import ContactRepository
from messaging.dispatcher import MessageDispatcher
from messaging.ivr.enums.ivr_enums import IvrExecutionStatus
from messaging.ivr.models.ivr_execution_model import IvrExecutionModel
from messaging.ivr.repository.ivr_execution_repository import IvrExecutionRepository
from messaging.provider_credentials.services.provider_credential_service import (
    MessagingProviderCredentialService,
)


class BatchSender:
    def __init__(
        self,
        dispatcher: MessageDispatcher,
        repo: ContactRepository,
        ivr_execution_repo: IvrExecutionRepository | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._repo = repo
        self._ivr_executions = ivr_execution_repo

    async def process_batch(
        self,
        inputs: list[SendInput],
        channel_name: str,
        phone_prefix: str | None = None,
        campaign_name: str | None = None,
        phone_number_id: str | None = None,
        language: str | None = None,
        credential_service: MessagingProviderCredentialService | None = None,
        country: str | None = None,
        channel_context: dict[str, Any] | None = None,
    ) -> BatchStats:
        if not inputs:
            return BatchStats()

        stats = BatchStats()
        unique_recipients: set[str] = set()
        sender = self._dispatcher.get_sender(channel_name)

        chunks = [inputs[i : i + BATCH_SIZE] for i in range(0, len(inputs), BATCH_SIZE)]

        for chunk in chunks:
            try:
                ok, fail = await self._send_chunk(
                    chunk,
                    channel_name,
                    sender.sends_per_recipient,
                    phone_prefix,
                    campaign_name,
                    phone_number_id,
                    language,
                    credential_service,
                    country,
                    channel_context,
                )
                stats.success_count += ok
                stats.failure_count += fail
                stats.total_sent += len(chunk)
                for inp in chunk:
                    unique_recipients.add(inp.recipient)
            except Exception:
                logger.exception(
                    "[batch_sender] error en chunk campaña=%s", inputs[0].campaign_id
                )
                stats.failure_count += len(chunk)
                stats.total_sent += len(chunk)

        stats.unique_customers = len(unique_recipients)
        return stats

    async def _send_with_retry(
        self,
        channel: str,
        to: list[str],
        message: str,
        **kwargs: Any,
    ) -> tuple[bool, str | None, dict[str, str] | None, str | None]:
        last_err: str | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                ok, ids_by_recipient, sending_id = await self._dispatcher.send(
                    channel, to, message, **kwargs
                )
                if ok:
                    return True, None, ids_by_recipient, sending_id
                last_err = "provider returned false"
            except Exception as exc:
                last_err = str(exc)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BASE_MS * (2 ** (attempt - 1)) / 1000)
        return False, last_err, None, None

    async def _persist_contact(
        self,
        inp: SendInput,
        status: ContactStatus,
        provider: ProviderType | None,
        external_id: str | None,
        sending_id: str | None,
        error: str | None,
        sent_at: datetime | None,
    ) -> None:
        contact = ContactModel(
            content=inp.content,
            recipient=inp.recipient,
            status=status,
            debtor_id=inp.debtor_id,
            debtor_document=inp.debtor_document,
            sent_at=sent_at,
            provider=provider,
            external_id=external_id,
            sending_id=sending_id,
            error=error,
            campaign_id=inp.campaign_id,
            organization_id=inp.organization_id,
            portfolio_id=inp.portfolio_id,
            snapshot_channel_id=inp.snapshot_channel_id,
            snapshot_currency=inp.snapshot_currency,
            snapshot_unit_price=inp.snapshot_unit_price,
        )
        # Aislado en su propio savepoint: un INSERT inválido (p. ej. dato
        # demasiado largo) no rompe la transacción de la campaña ni
        # impide persistir los demás contactos.
        # No se usa self._repo.add() a propósito: su refresh() posterior
        # es un round-trip extra que no hace falta acá (el objeto se
        # descarta, nadie lee sus campos server-side).
        try:
            await self._repo.add_isolated(contact)
        except Exception:
            logger.exception(
                "[batch_sender] no se pudo persistir contacto recipient=%s campaña=%s",
                inp.recipient,
                inp.campaign_id,
            )

    async def _persist_contacts_bulk(
        self,
        chunk: list[SendInput],
        status: ContactStatus,
        provider: ProviderType | None,
        ids_by_recipient: dict[str, str] | None,
        sending_id: str | None,
        error: str | None,
        sent_at: datetime | None,
    ) -> None:
        """Un solo INSERT multi-fila para todo el chunk, vía
        `ContactRepository.add_many_isolated`, en vez de un `add_isolated`
        -- 1 INSERT con su propio SAVEPOINT -- por destinatario. El
        proveedor ya respondió con un resultado único
        para todo el chunk antes de llegar acá, así que no hay nada que
        justifique un round trip por fila en el caso feliz. Si el bulk
        falla por algo no previsto (p. ej. un dato demasiado largo en una
        sola fila), cae al camino de hoy (fila por fila, aislado por
        SAVEPOINT) SOLO para este chunk -- nunca se pierde la garantía de
        que un contacto inválido no tumbe el resto del chunk."""
        contacts = [
            ContactModel(
                content=inp.content,
                recipient=inp.recipient,
                status=status,
                debtor_id=inp.debtor_id,
                debtor_document=inp.debtor_document,
                sent_at=sent_at,
                provider=provider,
                external_id=(
                    ids_by_recipient.get(inp.recipient) if ids_by_recipient else None
                ),
                sending_id=sending_id,
                error=error,
                campaign_id=inp.campaign_id,
                organization_id=inp.organization_id,
                portfolio_id=inp.portfolio_id,
                snapshot_channel_id=inp.snapshot_channel_id,
                snapshot_currency=inp.snapshot_currency,
                snapshot_unit_price=inp.snapshot_unit_price,
            )
            for inp in chunk
        ]
        try:
            await self._repo.add_many_isolated(contacts)
        except Exception:
            logger.exception(
                "[batch_sender] bulk insert de contactos falló, "
                "reintentando fila por fila | campaña=%s tamaño=%d",
                chunk[0].campaign_id if chunk else None,
                len(chunk),
            )
            for inp in chunk:
                external_id = (
                    ids_by_recipient.get(inp.recipient) if ids_by_recipient else None
                )
                await self._persist_contact(
                    inp, status, provider, external_id, sending_id, error, sent_at
                )

    async def _send_chunk(
        self,
        chunk: list[SendInput],
        channel_name: str,
        sends_per_recipient: bool,
        phone_prefix: str | None = None,
        campaign_name: str | None = None,
        phone_number_id: str | None = None,
        language: str | None = None,
        credential_service: MessagingProviderCredentialService | None = None,
        country: str | None = None,
        channel_context: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        # Justo antes de armar el "to": si el canal es telefónico y hay
        # indicativo del país (según el portafolio), se antepone al
        # número. Se persiste el número ya normalizado.
        if phone_prefix and is_phone_channel(channel_name):
            for inp in chunk:
                inp.recipient = normalize_phone(inp.recipient, phone_prefix)
        if sends_per_recipient:
            return await self._send_individually(
                chunk,
                channel_name,
                campaign_name,
                phone_number_id,
                language,
                credential_service,
                country,
            )
        return await self._send_bulk(
            chunk,
            channel_name,
            channel_context,
            credential_service=credential_service,
            country=country,
            campaign_name=campaign_name,
        )

    async def _send_individually(
        self,
        chunk: list[SendInput],
        channel_name: str,
        campaign_name: str | None = None,
        phone_number_id: str | None = None,
        language: str | None = None,
        credential_service: MessagingProviderCredentialService | None = None,
        country: str | None = None,
    ) -> tuple[int, int]:
        success = 0
        failure = 0
        provider = provider_for_channel(channel_name)
        for inp in chunk:
            ok, err, ids_by_recipient, sending_id = await self._send_with_retry(
                channel_name,
                [inp.recipient],
                inp.content,
                subject=inp.subject or "",
                sub=inp.sub,
                campaign_name=campaign_name,
                phone_number_id=phone_number_id,
                language=language,
                credential_service=credential_service,
                country=country,
            )
            now = datetime.now(timezone.utc) if ok else None
            status = ContactStatus.SENT if ok else ContactStatus.FAILED
            external_id = (
                ids_by_recipient.get(inp.recipient) if ids_by_recipient else None
            )
            await self._persist_contact(
                inp, status, provider, external_id, sending_id, err, now
            )
            if ok:
                success += 1
            else:
                failure += 1
        return success, failure

    async def _send_bulk(
        self,
        chunk: list[SendInput],
        channel_name: str,
        channel_context: dict[str, Any] | None = None,
        campaign_name: str | None = None,
        sender: str = "Template",
        credential_service: MessagingProviderCredentialService | None = None,
        country: str | None = None,
    ) -> tuple[int, int]:
        to = [inp.recipient for inp in chunk]
        # ``sub`` va alineado posicionalmente al ``to``. Si ningún
        # destinatario del chunk tiene variables (mensaje sin
        # placeholders), se omite por completo: 360nrs rechaza dicts
        # vacíos. Si al menos uno tiene datos, se conserva la lista (con
        # ``{}`` para los que no) para no romper la alineación.
        sub_list = [inp.sub[0] if inp.sub else {} for inp in chunk]
        sub = sub_list if any(sub_list) else None
        message = chunk[0].content
        provider = provider_for_channel(channel_name)

        extra_kwargs: dict[str, Any] = {}
        if channel_context is not None:
            # Canal IVR (Helena): entrega el flujo + destinatarios estructurados.
            extra_kwargs["ivr_context"] = channel_context
            extra_kwargs["targets"] = [
                {"phone": inp.recipient, "document": inp.debtor_document}
                for inp in chunk
            ]

        ok, err, ids_by_recipient, sending_id = await self._send_with_retry(
            channel_name,
            to,
            message,
            sender=sender,
            sub=sub,
            campaign_name=campaign_name,
            credential_service=credential_service,
            country=country,
            **extra_kwargs,
        )
        now = datetime.now(timezone.utc) if ok else None
        status = ContactStatus.SENT if ok else ContactStatus.FAILED

        await self._persist_contacts_bulk(
            chunk, status, provider, ids_by_recipient, sending_id, err, now
        )

        if sending_id:
            await self._record_ivr_execution(chunk, channel_context, sending_id)

        return (len(chunk), 0) if ok else (0, len(chunk))

    async def _record_ivr_execution(
        self,
        chunk: list[SendInput],
        channel_context: dict[str, Any] | None,
        bulk_id: str,
    ) -> None:
        """Registra el bulk despachado a Helena en `ejecuciones_ivr`.

        Se crea aquí, no en el provider: el provider es HTTP puro y se
        construye una sola vez a nivel de proceso (`_DISPATCHER` es un
        singleton en `automation_service.py`), sin sesión de base de datos.
        `sending_id` presente significa que Helena encoló el bulk (aunque el
        `ok` general del chunk pueda variar por otros motivos), así que sí hay
        algo que trazar.
        """
        if self._ivr_executions is None or channel_context is None:
            return
        raw_campaign_id = channel_context.get("campaign_id")
        if not raw_campaign_id:
            return

        try:
            campaign_id = uuid.UUID(str(raw_campaign_id))
        except ValueError:
            logger.warning(
                "[batch_sender] campaign_id inválido en channel_context: %r",
                raw_campaign_id,
            )
            return

        raw_ct_id = channel_context.get("campaign_time_id")
        campaign_time_id: uuid.UUID | None = None
        if raw_ct_id:
            try:
                campaign_time_id = uuid.UUID(str(raw_ct_id))
            except ValueError:
                pass

        execution = IvrExecutionModel(
            bulk_id=bulk_id,
            campaign_id=campaign_id,
            campaign_time_id=campaign_time_id,
            organization_id=chunk[0].organization_id,
            status=IvrExecutionStatus.RUNNING,
            quantity=len(chunk),
            calls_per_second=channel_context.get("calls_per_second"),
            max_concurrent=channel_context.get("max_concurrent"),
            dispatched_at=datetime.now(timezone.utc),
        )
        await self._ivr_executions.add(execution)
