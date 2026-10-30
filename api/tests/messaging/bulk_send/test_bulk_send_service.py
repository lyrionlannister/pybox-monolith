"""Tests de `BulkSendService.process` (envío masivo manual desde archivo cargado, ver
bulk_send_service.py). Riesgos reales cubiertos:

- El bloqueo por facturación (402) corta ANTES de tocar canal/plantilla/filas -- un
  webhook de pago atrasado no debe dejar seguir enviando.
- WhatsApp exige plantilla guardada: mandar `body` inline se rechaza con 422, y sin
  `templateId` ni `body` también se rechaza (mismo mensaje, otro branch del código).
- Parseo de filas: destinatario vacío o duplicado se cuenta como omitida, no revienta
  el batch; `tipo_documento` inválido igual se omite (no aborta el resto del archivo).
- WhatsApp sin caso de consentimiento aprobado se cuenta aparte (`pending_approval`),
  no se envía ni se cuenta como omitida.

Unitarios puros: todos los repos/servicios inyectados van mockeados con
`unittest.mock` (no hay pytest-mock, ver test_bold_webhook.py). `_country_repo` y
`_credential_service` se pisan después de construir el servicio porque el `__init__`
real los instancia con la sesión del `portfolio_repo` (mockeada, no habla con
Postgres) -- sin este parche `get_phone_prefix` tumbaría el test con un `MagicMock`
no-awaitable en vez de un resultado real.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from messaging.bulk_send.services.bulk_send_service import BulkSendService
from messaging.campaigns.schemas.batch_schemas import BatchStats
from messaging.channels.enums.channel_enums import ChannelName
from messaging.whatsapp.enums.whatsapp_enums import ChannelRequestStatus


def build_service(**overrides) -> tuple[BulkSendService, dict]:
    mocks = dict(
        debtor_repo=MagicMock(),
        channel_repo=MagicMock(),
        template_repo=MagicMock(),
        portfolio_repo=MagicMock(),
        campaign_repo=MagicMock(),
        batch_sender=MagicMock(),
        billing_status_service=MagicMock(),
        whatsapp_credentials_repo=MagicMock(),
        whatsapp_template_data_repo=MagicMock(),
        whatsapp_channel_request_service=MagicMock(),
        whatsapp_number_request_service=MagicMock(),
    )
    mocks["portfolio_repo"].session = MagicMock()
    mocks.update(overrides)

    service = BulkSendService(**mocks)
    # Pisa las dos instancias reales creadas en __init__ (ver docstring del módulo).
    service._country_repo = AsyncMock()
    service._country_repo.get_phone_prefix = AsyncMock(return_value="57")
    service._credential_service = MagicMock()
    return service, mocks


def make_portfolio(**overrides):
    portfolio = MagicMock()
    portfolio.id = overrides.pop("id", uuid.uuid4())
    portfolio.organization_id = overrides.pop("organization_id", uuid.uuid4())
    portfolio.country = overrides.pop("country", "CO")
    for key, value in overrides.items():
        setattr(portfolio, key, value)
    return portfolio


def make_channel(name: ChannelName, **overrides):
    channel = MagicMock()
    channel.id = overrides.pop("id", uuid.uuid4())
    channel.name = name
    channel.label = overrides.pop("label", "Email")
    channel.currency = overrides.pop("currency", "COP")
    channel.unit_price = overrides.pop("unit_price", 100)
    return channel


def make_user_session():
    session = MagicMock()
    session.is_global = True
    session.user_id = uuid.uuid4()
    return session


class TestProcessBillingBlock:
    async def test_blocked_organization_raises_402_before_touching_channel(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=True)

        with pytest.raises(HTTPException) as exc_info:
            await service.process(
                portfolio_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                rows=[
                    {
                        "tipo_documento": "CC",
                        "documento": "1",
                        "destinatario": "a@b.com",
                    }
                ],
                user_session=make_user_session(),
                template_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 402
        mocks["channel_repo"].get_by_id.assert_not_called()


class TestProcessChannelNotFound:
    async def test_missing_channel_raises_404(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await service.process(
                portfolio_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                rows=[],
                user_session=make_user_session(),
                template_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 404


class TestProcessEmailRequiresSubject:
    async def test_email_channel_without_subject_raises_422(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.EMAIL)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.process(
                portfolio_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                rows=[],
                user_session=make_user_session(),
                body="hola",
                subject=None,
            )

        assert exc_info.value.status_code == 422
        assert "subject" in exc_info.value.detail


class TestProcessWhatsAppRequiresTemplate:
    async def test_whatsapp_with_inline_body_is_rejected(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.WHATSAPP)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.process(
                portfolio_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                rows=[],
                user_session=make_user_session(),
                body="contenido inline, no permitido",
            )

        assert exc_info.value.status_code == 422
        assert "templateId" in exc_info.value.detail

    async def test_whatsapp_without_template_id_or_body_is_rejected(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.WHATSAPP)
        )
        credentials = MagicMock(active=True, phone_number_id="pnid-1")
        mocks["whatsapp_credentials_repo"].get_by_organization = AsyncMock(
            return_value=credentials
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.process(
                portfolio_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                rows=[],
                user_session=make_user_session(),
                # Sin template_id ni body.
            )

        assert exc_info.value.status_code == 422
        assert "templateId" in exc_info.value.detail

    async def test_whatsapp_without_active_credentials_requests_provisioning(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.WHATSAPP)
        )
        mocks["whatsapp_credentials_repo"].get_by_organization = AsyncMock(
            return_value=None
        )
        mocks["whatsapp_number_request_service"].ensure_number_available = AsyncMock(
            return_value=False
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.process(
                portfolio_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                rows=[],
                user_session=make_user_session(),
                template_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 422
        mocks[
            "whatsapp_number_request_service"
        ].ensure_number_available.assert_awaited_once()


class TestProcessTemplateResolution:
    async def test_unknown_template_id_raises_404(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.EMAIL)
        )
        mocks["template_repo"].get_by_id_and_portfolio = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await service.process(
                portfolio_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                rows=[],
                user_session=make_user_session(),
                template_id=uuid.uuid4(),
                subject="asunto",
            )

        assert exc_info.value.status_code == 404

    async def test_no_template_id_and_no_body_raises_422(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.EMAIL)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.process(
                portfolio_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                rows=[],
                user_session=make_user_session(),
                subject="asunto",
            )

        assert exc_info.value.status_code == 422
        assert "templateId" in exc_info.value.detail


class TestProcessRowParsing:
    def _setup_email(self, mocks):
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.EMAIL)
        )
        mocks["campaign_repo"].get_or_create_manual = AsyncMock(
            return_value=MagicMock(id=uuid.uuid4(), name="Envío Manual — Email")
        )
        mocks["debtor_repo"].get_by_document_hashes = AsyncMock(return_value=[])
        mocks["batch_sender"].process_batch = AsyncMock(
            return_value=BatchStats(
                total_sent=0, success_count=0, failure_count=0, unique_customers=0
            )
        )

    async def test_empty_recipient_row_is_skipped(self):
        service, mocks = build_service()
        self._setup_email(mocks)

        response = await service.process(
            portfolio_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            rows=[{"tipo_documento": "CC", "documento": "1", "destinatario": ""}],
            user_session=make_user_session(),
            body="hola",
            subject="asunto",
        )

        assert response.skipped_rows == 1
        assert response.total_sent == 0
        mocks["batch_sender"].process_batch.assert_not_called()

    async def test_duplicate_recipient_rows_are_skipped_after_the_first(self):
        service, mocks = build_service()
        self._setup_email(mocks)

        rows = [
            {"tipo_documento": "CC", "documento": "1", "destinatario": "a@b.com"},
            {"tipo_documento": "CC", "documento": "1", "destinatario": "a@b.com"},
        ]
        response = await service.process(
            portfolio_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            rows=rows,
            user_session=make_user_session(),
            body="hola",
            subject="asunto",
        )

        assert response.skipped_rows == 1
        mocks["batch_sender"].process_batch.assert_awaited_once()
        sent_inputs = mocks["batch_sender"].process_batch.await_args.args[0]
        assert len(sent_inputs) == 1

    async def test_invalid_tipo_documento_is_skipped_without_aborting_batch(self):
        service, mocks = build_service()
        self._setup_email(mocks)

        rows = [
            {
                "tipo_documento": "NO-EXISTE",
                "documento": "1",
                "destinatario": "a@b.com",
            },
            {"tipo_documento": "CC", "documento": "2", "destinatario": "c@d.com"},
        ]
        response = await service.process(
            portfolio_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            rows=rows,
            user_session=make_user_session(),
            body="hola",
            subject="asunto",
        )

        assert response.skipped_rows == 1
        sent_inputs = mocks["batch_sender"].process_batch.await_args.args[0]
        assert len(sent_inputs) == 1
        assert sent_inputs[0].recipient == "c@d.com"

    async def test_row_variables_exclude_reserved_columns(self):
        service, mocks = build_service()
        self._setup_email(mocks)

        rows = [
            {
                "tipo_documento": "CC",
                "documento": "1",
                "destinatario": "a@b.com",
                "nombre": "Ana",
            }
        ]
        await service.process(
            portfolio_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            rows=rows,
            user_session=make_user_session(),
            body="hola {nombre}",
            subject="asunto",
        )

        sent_inputs = mocks["batch_sender"].process_batch.await_args.args[0]
        assert sent_inputs[0].sub == [{"nombre": "Ana"}]

    async def test_no_valid_rows_returns_zeroed_response_without_calling_batch_sender(
        self,
    ):
        service, mocks = build_service()
        self._setup_email(mocks)

        response = await service.process(
            portfolio_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            rows=[{"tipo_documento": "CC", "documento": "1", "destinatario": ""}],
            user_session=make_user_session(),
            body="hola",
            subject="asunto",
        )

        assert response.total_sent == 0
        assert response.success_count == 0
        assert response.failure_count == 0
        assert response.unique_customers == 0
        mocks["batch_sender"].process_batch.assert_not_called()


class TestProcessWhatsAppConsentGate:
    async def test_recipient_without_approved_consent_counts_as_pending_not_sent(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.WHATSAPP)
        )
        credentials = MagicMock(active=True, phone_number_id="pnid-1")
        mocks["whatsapp_credentials_repo"].get_by_organization = AsyncMock(
            return_value=credentials
        )
        whatsapp_data = MagicMock(meta_name="plantilla_meta", language="es")
        mocks["whatsapp_template_data_repo"].get_by_template_id = AsyncMock(
            return_value=whatsapp_data
        )
        template = MagicMock(id=uuid.uuid4(), channel=ChannelName.WHATSAPP)
        mocks["template_repo"].get_by_id_and_portfolio = AsyncMock(
            return_value=template
        )
        mocks["campaign_repo"].get_or_create_manual = AsyncMock(
            return_value=MagicMock(id=uuid.uuid4(), name="Envío Manual — WhatsApp")
        )
        mocks["debtor_repo"].get_by_document_hashes = AsyncMock(return_value=[])
        mocks["whatsapp_channel_request_service"].get_existing_statuses = AsyncMock(
            return_value={"573001112233": ChannelRequestStatus.PENDING}
        )

        response = await service.process(
            portfolio_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            rows=[
                {"tipo_documento": "CC", "documento": "1", "destinatario": "3001112233"}
            ],
            user_session=make_user_session(),
            template_id=uuid.uuid4(),
        )

        assert response.pending_approval_count == 1
        assert response.total_sent == 0
        mocks["batch_sender"].process_batch.assert_not_called()

    async def test_recipient_without_existing_case_creates_one_via_bulk(self):
        """Teléfono sin caso previo (`get_existing_statuses` no lo trae): debe crearse
        vía `ensure_cases_bulk` (un solo INSERT masivo), no `ensure_case` fila por
        fila, y queda PENDIENTE por default -- no se envía en el mismo batch."""
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.WHATSAPP)
        )
        credentials = MagicMock(active=True, phone_number_id="pnid-1")
        mocks["whatsapp_credentials_repo"].get_by_organization = AsyncMock(
            return_value=credentials
        )
        whatsapp_data = MagicMock(meta_name="plantilla_meta", language="es")
        mocks["whatsapp_template_data_repo"].get_by_template_id = AsyncMock(
            return_value=whatsapp_data
        )
        template = MagicMock(id=uuid.uuid4(), channel=ChannelName.WHATSAPP)
        mocks["template_repo"].get_by_id_and_portfolio = AsyncMock(
            return_value=template
        )
        mocks["campaign_repo"].get_or_create_manual = AsyncMock(
            return_value=MagicMock(id=uuid.uuid4(), name="Envío Manual — WhatsApp")
        )
        mocks["debtor_repo"].get_by_document_hashes = AsyncMock(return_value=[])
        mocks["whatsapp_channel_request_service"].get_existing_statuses = AsyncMock(
            return_value={}
        )
        mocks["whatsapp_channel_request_service"].ensure_cases_bulk = AsyncMock()

        response = await service.process(
            portfolio_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            rows=[
                {"tipo_documento": "CC", "documento": "1", "destinatario": "3001112233"}
            ],
            user_session=make_user_session(),
            template_id=uuid.uuid4(),
        )

        assert response.pending_approval_count == 1
        assert response.total_sent == 0
        mocks[
            "whatsapp_channel_request_service"
        ].ensure_cases_bulk.assert_awaited_once()
        mocks["whatsapp_channel_request_service"].ensure_case.assert_not_called()

    async def test_recipient_with_approved_consent_is_sent(self):
        service, mocks = build_service()
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=make_portfolio())
        mocks["billing_status_service"].is_blocked = AsyncMock(return_value=False)
        mocks["channel_repo"].get_by_id = AsyncMock(
            return_value=make_channel(ChannelName.WHATSAPP)
        )
        credentials = MagicMock(active=True, phone_number_id="pnid-1")
        mocks["whatsapp_credentials_repo"].get_by_organization = AsyncMock(
            return_value=credentials
        )
        whatsapp_data = MagicMock(meta_name="plantilla_meta", language="es")
        mocks["whatsapp_template_data_repo"].get_by_template_id = AsyncMock(
            return_value=whatsapp_data
        )
        template = MagicMock(id=uuid.uuid4(), channel=ChannelName.WHATSAPP)
        mocks["template_repo"].get_by_id_and_portfolio = AsyncMock(
            return_value=template
        )
        mocks["campaign_repo"].get_or_create_manual = AsyncMock(
            return_value=MagicMock(id=uuid.uuid4(), name="Envío Manual — WhatsApp")
        )
        mocks["debtor_repo"].get_by_document_hashes = AsyncMock(return_value=[])
        mocks["whatsapp_channel_request_service"].get_existing_statuses = AsyncMock(
            return_value={"573001112233": ChannelRequestStatus.APPROVED}
        )
        mocks["batch_sender"].process_batch = AsyncMock(
            return_value=BatchStats(
                total_sent=1, success_count=1, failure_count=0, unique_customers=1
            )
        )

        response = await service.process(
            portfolio_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            rows=[
                {"tipo_documento": "CC", "documento": "1", "destinatario": "3001112233"}
            ],
            user_session=make_user_session(),
            template_id=uuid.uuid4(),
        )

        assert response.pending_approval_count == 0
        assert response.total_sent == 1
        mocks["batch_sender"].process_batch.assert_awaited_once()
