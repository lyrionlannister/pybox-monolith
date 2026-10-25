"""Creación de transacciones de cobro (checkout) contra la pasarela de cobro."""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status

from identity.users.schemas.user_session_schema import UserSession
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ChargeMode,
    ReceivablesGatewayProvider,
    ReceivablesPaymentAttemptStatus,
)
from receivables.payment_gateways.gateways.base import (
    BrowserInfo,
    DeviceInfo,
    GatewayFinancialInstitution,
    OtpChallenge,
    PaymentMethodInput,
    RedirectAction,
    ThreeDsChallenge,
)
from receivables.payment_gateways.gateways.resolver import ReceivablesGatewayResolver
from receivables.payment_gateways.models.payment_attempt_model import (
    CreditPaymentAttemptModel,
)
from receivables.payment_gateways.repository.payment_attempt_repository import (
    CreditPaymentAttemptRepository,
)
from receivables.payment_gateways.utils.attempt_status_sync import (
    sync_attempt_with_transaction,
)
from receivables.payment_gateways.utils.reference_utils import (
    build_payment_reference,
    to_amount_in_cents,
)
from receivables.payment_gateways.utils.wompi_status_mapping import to_attempt_status
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.payments.services.payment_ownership_resolver import (
    PaymentOwnershipResolver,
)

_CURRENCY = "COP"


class PaymentCheckoutService:
    """Autoservicio del titular (scope SELF): inicia un cobro puntual (`CHECKOUT`, el
    deudor esta presente y confirma) de UNA cuota pendiente contra la pasarela de la
    organizacion dueña del credito. Reutiliza `PaymentOwnershipResolver` — misma cadena
    de pertenencia que `PaymentSelfServiceService` (ver skill `tenant-isolation`)."""

    def __init__(
        self,
        ownership_resolver: PaymentOwnershipResolver,
        attempt_repo: CreditPaymentAttemptRepository,
        gateway_resolver: ReceivablesGatewayResolver,
        payment_repo: PaymentRepository,
    ) -> None:
        self._ownership_resolver = ownership_resolver
        self._attempt_repo = attempt_repo
        self._gateway_resolver = gateway_resolver
        self._payment_repo = payment_repo

    async def create_transaction(
        self,
        session: UserSession,
        payment_id: uuid.UUID,
        payment_method: PaymentMethodInput,
        customer_email: str,
        browser_info: BrowserInfo | None = None,
        device_info: DeviceInfo | None = None,
    ) -> tuple[
        CreditPaymentAttemptModel,
        ThreeDsChallenge | None,
        RedirectAction | None,
        OtpChallenge | None,
    ]:
        (
            payment,
            _credit,
            portfolio,
        ) = await self._ownership_resolver.resolve_owned_payment(session, payment_id)

        gateway = await self._gateway_resolver.get_active_for_organization(
            portfolio.organization_id
        )
        if gateway is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Esta organización no tiene una pasarela de pago configurada.",
            )

        tokens = await gateway.get_acceptance_tokens()

        latest_attempt = await self._attempt_repo.get_latest_by_payment_id(payment.id)
        attempt_number = (latest_attempt.attempt_number + 1) if latest_attempt else 1
        amount_in_cents = to_amount_in_cents(payment.payment_amount)
        reference = build_payment_reference(payment.id, attempt_number)

        transaction = await gateway.create_transaction(
            reference=reference,
            amount_in_cents=amount_in_cents,
            currency=_CURRENCY,
            payment_method=payment_method,
            acceptance_token=tokens.acceptance_token,
            accept_personal_auth=tokens.personal_data_token,
            customer_email=customer_email,
            browser_info=browser_info,
            device_info=device_info,
        )

        attempt = await self._attempt_repo.add(
            CreditPaymentAttemptModel(
                payment_id=payment.id,
                attempt_number=attempt_number,
                provider=ReceivablesGatewayProvider(gateway.name),
                charge_mode=ChargeMode.CHECKOUT,
                provider_reference=reference,
                provider_transaction_id=transaction.id,
                expected_amount_cents=amount_in_cents,
                status=to_attempt_status(transaction.status),
                provider_payload=transaction.raw,
                acceptance_permalink=tokens.acceptance_permalink,
                personal_data_permalink=tokens.personal_data_permalink,
                accepted_at=datetime.now(timezone.utc),
            )
        )
        return (
            attempt,
            transaction.three_ds_challenge,
            transaction.redirect_action,
            transaction.otp_challenge,
        )

    async def resolve_by_reference(
        self, session: UserSession, reference: str
    ) -> CreditPaymentAttemptModel:
        """Para el retorno de una redirección (Bold: PSE, Botón Bancolombia, 3DS) -- el
        deudor vuelve a `RECEIVABLES_PAYMENT_REDIRECT_RETURN_URL?reference=...` sin
        conocer de antemano el `payment_id`/`attempt_id` que el frontend necesita para
        seguir el polling habitual. ePayco nunca acepta nuestra propia referencia (ver
        `EpaycoGateway._build_response_url`): su URL de retorno solo trae `ref_payco`,
        guardado como `provider_transaction_id`, no como `provider_reference` -- de ahí
        el fallback."""
        attempt = await self._attempt_repo.get_by_provider_reference(
            reference
        ) or await self._attempt_repo.get_by_provider_transaction_id(reference)
        if attempt is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Intento de pago no encontrado."
            )
        # Misma cadena de pertenencia que el resto del modulo (ver skill
        # tenant-isolation): 404 generico si la referencia no corresponde a un intento
        # del propio deudor autenticado.
        await self._ownership_resolver.resolve_owned_payment(
            session, attempt.payment_id, require_pending=False
        )
        return attempt

    async def list_pse_institutions(
        self, session: UserSession, payment_id: uuid.UUID
    ) -> list[GatewayFinancialInstitution]:
        (
            _payment,
            _credit,
            portfolio,
        ) = await self._ownership_resolver.resolve_owned_payment(
            session, payment_id, require_pending=False
        )
        gateway = await self._gateway_resolver.get_active_for_organization(
            portfolio.organization_id
        )
        if gateway is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Esta organización no tiene una pasarela de pago configurada.",
            )
        return await gateway.list_pse_financial_institutions()

    async def confirm_daviplata_otp(
        self,
        session: UserSession,
        payment_id: uuid.UUID,
        attempt_id: uuid.UUID,
        otp: str,
    ) -> CreditPaymentAttemptModel:
        """Segundo paso de Daviplata (ePayco, ver `OtpChallenge`). El `idSessionToken`
        se lee del payload guardado al crear el intento -- nunca viaja al cliente."""
        (
            payment,
            _credit,
            portfolio,
        ) = await self._ownership_resolver.resolve_owned_payment(
            session, payment_id, require_pending=False
        )
        attempt = await self._attempt_repo.get_by_id(attempt_id)
        # 404 generico, mismo criterio IDOR que `refresh_attempt_status`.
        if attempt is None or attempt.payment_id != payment.id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Intento de pago no encontrado."
            )
        if attempt.status != ReceivablesPaymentAttemptStatus.PENDING:
            return attempt

        transaction_data = ((attempt.provider_payload or {}).get("data") or {}).get(
            "transaction"
        ) or {}
        id_session_token = transaction_data.get("idSessionToken")
        if (
            attempt.provider != ReceivablesGatewayProvider.EPAYCO
            or not id_session_token
            or not attempt.provider_transaction_id
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Este intento de pago no espera un código de Daviplata.",
            )

        gateway = await self._gateway_resolver.get_active_for_organization(
            portfolio.organization_id
        )
        if gateway is None or gateway.name != attempt.provider.value:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "La pasarela de este intento ya no está activa.",
            )

        transaction = await gateway.confirm_daviplata_otp(
            attempt.provider_transaction_id, str(id_session_token), otp
        )
        await sync_attempt_with_transaction(
            attempt, transaction, self._attempt_repo, self._payment_repo
        )
        return attempt

    async def refresh_attempt_status(
        self, session: UserSession, payment_id: uuid.UUID, attempt_id: uuid.UUID
    ) -> CreditPaymentAttemptModel:
        (
            payment,
            _credit,
            portfolio,
        ) = await self._ownership_resolver.resolve_owned_payment(
            session, payment_id, require_pending=False
        )
        attempt = await self._attempt_repo.get_by_id(attempt_id)
        # 404 generico (no 403): mismo criterio IDOR que el resto del modulo -- un
        # intento ajeno no debe poder confirmarse por el codigo de error.
        if attempt is None or attempt.payment_id != payment.id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Intento de pago no encontrado."
            )
        if attempt.status != ReceivablesPaymentAttemptStatus.PENDING:
            return attempt

        gateway = await self._gateway_resolver.get_active_for_organization(
            portfolio.organization_id
        )
        if gateway is None or not attempt.provider_transaction_id:
            return attempt

        transaction = await gateway.get_transaction(attempt.provider_transaction_id)
        await sync_attempt_with_transaction(
            attempt, transaction, self._attempt_repo, self._payment_repo
        )
        return attempt
