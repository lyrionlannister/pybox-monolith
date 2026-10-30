"""Cobro automático (recurrente) de cuotas contra la pasarela de la organización."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from core.config.logger import logger
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ChargeMode,
    ReceivablesGatewayProvider,
    ReceivablesPaymentAttemptStatus,
)
from receivables.payment_gateways.gateways.resolver import ReceivablesGatewayResolver
from receivables.payment_gateways.models.payment_attempt_model import (
    CreditPaymentAttemptModel,
)
from receivables.payment_gateways.repository.payment_attempt_repository import (
    CreditPaymentAttemptRepository,
)
from receivables.payment_gateways.repository.payment_source_repository import (
    DebtorPaymentSourceRepository,
)
from receivables.payment_gateways.utils.reference_utils import (
    build_payment_reference,
    to_amount_in_cents,
)
from receivables.payment_gateways.utils.wompi_status_mapping import to_attempt_status
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository

_CURRENCY = "COP"
_ELIGIBLE_BRAND = "MASTERCARD"


@dataclass(frozen=True)
class AutomaticChargeOutcome:
    charged: bool
    attempt: CreditPaymentAttemptModel | None
    reason: str


class AutomaticChargeService:
    """Decide si una cuota se cobra en silencio (3RI) o si requiere que el deudor
    confirme el pago cada vez (skill `wompi-gateway`, Paso 6). Sin `UserSession`:
    pensado para invocarse desde un cron futuro (mismo patrón que
    `billing/invoices/cron.py` -> `run_overdue_transitions`), no desde un endpoint de
    usuario — por eso resuelve la cadena de pertenencia por repositorio directo, sin
    pasar por `PaymentOwnershipResolver` (que exige una sesión SELF).

    NO envía la notificación de "confirma tu pago cada vez" cuando no es elegible para
    3RI — eso es un canal de mensajería que queda fuera de alcance de esta tarea (ver
    plan). Esta clase solo decide el camino y, cuando aplica, ejecuta el cobro 3RI real;
    cuando no aplica, deja dicho explícitamente por qué."""

    def __init__(
        self,
        payment_repo: PaymentRepository,
        credit_repo: CreditRepository,
        portfolio_repo: PortfolioRepository,
        source_repo: DebtorPaymentSourceRepository,
        attempt_repo: CreditPaymentAttemptRepository,
        gateway_resolver: ReceivablesGatewayResolver,
    ) -> None:
        self._payment_repo = payment_repo
        self._credit_repo = credit_repo
        self._portfolio_repo = portfolio_repo
        self._source_repo = source_repo
        self._attempt_repo = attempt_repo
        self._gateway_resolver = gateway_resolver

    async def charge_or_request_confirmation(
        self, payment_id: uuid.UUID, customer_email: str
    ) -> AutomaticChargeOutcome:
        payment = await self._payment_repo.get_by_id(payment_id)
        if payment is None:
            return AutomaticChargeOutcome(False, None, "Cuota no encontrada.")

        credit = await self._credit_repo.get_by_id(payment.credit_id)
        if credit is None:
            return AutomaticChargeOutcome(False, None, "Crédito no encontrado.")

        portfolio = await self._portfolio_repo.get_by_id(credit.portfolio_id)
        if portfolio is None:
            return AutomaticChargeOutcome(False, None, "Portafolio no encontrado.")

        source = await self._source_repo.get_active_by_debtor_and_provider(
            credit.debtor_id, ReceivablesGatewayProvider.WOMPI
        )
        if source is None:
            return AutomaticChargeOutcome(
                False, None, "El deudor no tiene un medio de pago guardado."
            )

        gateway = await self._gateway_resolver.get_for_organization(
            portfolio.organization_id, ReceivablesGatewayProvider.WOMPI
        )
        if gateway is None:
            return AutomaticChargeOutcome(
                False, None, "La organización no tiene Wompi configurado."
            )

        eligible_for_silent_charge = (
            source.three_ds_enrolled
            and (source.brand or "").upper() == _ELIGIBLE_BRAND
            and gateway.supports_automatic_charge()
        )
        if not eligible_for_silent_charge:
            return AutomaticChargeOutcome(
                False,
                None,
                "Requiere confirmación del deudor: la fuente no está habilitada "
                "para 3RI (Mastercard + challenge 3DS) o la organización no "
                "tiene la activación de fraude de Wompi.",
            )

        tokens = await gateway.get_acceptance_tokens()
        latest_attempt = await self._attempt_repo.get_latest_by_payment_id(
            payment.id, for_update=True
        )
        if latest_attempt is not None and latest_attempt.status in (
            ReceivablesPaymentAttemptStatus.PENDING,
            ReceivablesPaymentAttemptStatus.APPROVED,
        ):
            return AutomaticChargeOutcome(
                False, None, "Ya hay un intento de cobro en curso para esta cuota."
            )
        attempt_number = (latest_attempt.attempt_number + 1) if latest_attempt else 1
        amount_in_cents = to_amount_in_cents(payment.payment_amount)
        reference = build_payment_reference(payment.id, attempt_number)

        transaction = await gateway.create_transaction(
            reference=reference,
            amount_in_cents=amount_in_cents,
            currency=_CURRENCY,
            payment_method=None,
            acceptance_token=tokens.acceptance_token,
            accept_personal_auth=tokens.personal_data_token,
            customer_email=customer_email,
            payment_source_id=source.provider_source_id,
        )

        attempt = await self._attempt_repo.add(
            CreditPaymentAttemptModel(
                payment_id=payment.id,
                attempt_number=attempt_number,
                provider=ReceivablesGatewayProvider.WOMPI,
                charge_mode=ChargeMode.AUTOMATIC_3RI,
                provider_reference=reference,
                provider_transaction_id=transaction.id,
                payment_source_id=source.id,
                expected_amount_cents=transaction.amount_in_cents,
                status=to_attempt_status(transaction.status),
                provider_payload=transaction.raw,
                accepted_at=datetime.now(timezone.utc),
            )
        )
        logger.info(
            "[receivables][wompi-3ri] cobro automatico intentado | payment=%s "
            "attempt=%s estado=%s",
            payment.id,
            attempt.id,
            attempt.status,
        )
        return AutomaticChargeOutcome(True, attempt, "Cobro automático 3RI ejecutado.")
