"""Endpoints de checkout: fuentes de pago guardadas y creación de transacciones."""

import uuid

from fastapi import Request, status

from core.config.api_router import APIRouter
from receivables.payment_gateways.dependencies import (
    PaymentCheckoutServiceDep,
    PaymentSourceServiceDep,
    RequireSelfForPaymentGateways,
)
from receivables.payment_gateways.gateways.base import (
    BancolombiaTransferPaymentMethod,
    BrowserInfo,
    CardPaymentMethod,
    DaviplataPaymentMethod,
    DeviceInfo,
    NequiPaymentMethod,
    PaymentMethodInput,
    PsePaymentMethod,
)
from receivables.payment_gateways.schemas.payment_checkout_schemas import (
    BancolombiaTransferTransactionRequest,
    CardTransactionRequest,
    DaviplataOtpConfirmRequest,
    DaviplataTransactionRequest,
    FinancialInstitutionResponse,
    NequiTransactionRequest,
    PaymentAttemptLookupResponse,
    PaymentAttemptResponse,
    PaymentSourceResponse,
    PseTransactionRequest,
    RedirectActionResponse,
    ThreeDsChallengeResponse,
    TokenizeCardSourceRequest,
    TokenizeNequiSourceRequest,
    TransactionCreationResponse,
    TransactionRequest,
)

router = APIRouter(prefix="/credits/payments", tags=["Cobro de cuotas"])


def _to_gateway_payment_method(body: TransactionRequest) -> PaymentMethodInput:
    if isinstance(body, CardTransactionRequest):
        return CardPaymentMethod(
            number=body.number,
            cvc=body.cvc,
            exp_month=body.exp_month,
            exp_year=body.exp_year,
            card_holder=body.card_holder,
            installments=body.installments,
        )
    if isinstance(body, PseTransactionRequest):
        return PsePaymentMethod(
            user_type=body.user_type,
            user_legal_id_type=body.user_legal_id_type,
            user_legal_id=body.user_legal_id,
            financial_institution_code=body.financial_institution_code,
            payment_description=body.payment_description,
        )
    if isinstance(body, NequiTransactionRequest):
        return NequiPaymentMethod(
            phone_number=body.phone_number,
            full_name=body.full_name,
            user_legal_id_type=body.user_legal_id_type,
            user_legal_id=body.user_legal_id,
            address=body.address,
            city=body.city,
        )
    if isinstance(body, BancolombiaTransferTransactionRequest):
        return BancolombiaTransferPaymentMethod(
            payment_description=body.payment_description,
            full_name=body.full_name,
            user_legal_id_type=body.user_legal_id_type,
            user_legal_id=body.user_legal_id,
            address=body.address,
            city=body.city,
        )
    if isinstance(body, DaviplataTransactionRequest):
        return DaviplataPaymentMethod(
            user_legal_id_type=body.user_legal_id_type,
            user_legal_id=body.user_legal_id,
            full_name=body.full_name,
            address=body.address,
            city=body.city,
            phone=body.phone,
        )
    raise ValueError(f"Tipo de método de pago no soportado: {type(body)!r}")


def _to_device_info(body: TransactionRequest, request: Request) -> DeviceInfo | None:
    """La IP sale de la petición (no del body): el cliente no puede falsearla."""
    device_info = getattr(body, "device_info", None)
    if device_info is None:
        return None
    return DeviceInfo(
        device_session_id=device_info.device_session_id,
        cookie=device_info.cookie,
        user_agent=device_info.user_agent,
        ip_address=request.client.host if request.client else "",
    )


def _to_attempt_response(attempt) -> PaymentAttemptResponse:
    return PaymentAttemptResponse(
        id=attempt.id,
        status=attempt.status.value,
        provider_reference=attempt.provider_reference,
        provider_transaction_id=attempt.provider_transaction_id,
        charge_mode=attempt.charge_mode.value,
    )


@router.post(
    "/{payment_id}/transaction",
    response_model=TransactionCreationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Iniciar el cobro de una cuota",
)
async def create_transaction(
    payment_id: uuid.UUID,
    body: TransactionRequest,
    request: Request,
    session: RequireSelfForPaymentGateways,
    service: PaymentCheckoutServiceDep,
) -> TransactionCreationResponse:
    browser_info = (
        BrowserInfo(
            browser_color_depth=body.browser_info.browser_color_depth,
            browser_screen_height=body.browser_info.browser_screen_height,
            browser_screen_width=body.browser_info.browser_screen_width,
            browser_language=body.browser_info.browser_language,
            browser_user_agent=body.browser_info.browser_user_agent,
            browser_tz=body.browser_info.browser_tz,
        )
        if isinstance(body, CardTransactionRequest)
        else None
    )
    (
        attempt,
        three_ds_challenge,
        redirect_action,
        otp_challenge,
    ) = await service.create_transaction(
        session,
        payment_id,
        _to_gateway_payment_method(body),
        body.customer_email,
        browser_info=browser_info,
        device_info=_to_device_info(body, request),
    )
    return TransactionCreationResponse(
        attempt=_to_attempt_response(attempt),
        three_ds_challenge=(
            ThreeDsChallengeResponse(
                current_step=three_ds_challenge.current_step,
                current_step_status=three_ds_challenge.current_step_status,
                challenge_html=three_ds_challenge.challenge_html,
            )
            if three_ds_challenge is not None
            else None
        ),
        redirect_action=(
            RedirectActionResponse(
                redirect_url=redirect_action.redirect_url,
                redirect_method=redirect_action.redirect_method,
            )
            if redirect_action is not None
            else None
        ),
        otp_required=otp_challenge is not None,
    )


@router.post(
    "/{payment_id}/transactions/{attempt_id}/daviplata/confirm-otp",
    response_model=PaymentAttemptResponse,
    summary="Confirmar un cobro Daviplata con el código OTP del deudor",
)
async def confirm_daviplata_otp(
    payment_id: uuid.UUID,
    attempt_id: uuid.UUID,
    body: DaviplataOtpConfirmRequest,
    session: RequireSelfForPaymentGateways,
    service: PaymentCheckoutServiceDep,
) -> PaymentAttemptResponse:
    attempt = await service.confirm_daviplata_otp(
        session, payment_id, attempt_id, body.otp
    )
    return _to_attempt_response(attempt)


@router.get(
    "/by-reference/{reference}",
    response_model=PaymentAttemptLookupResponse,
    summary="Resolver un intento de cobro por su referencia (retorno de redirección)",
)
async def get_transaction_by_reference(
    reference: str,
    session: RequireSelfForPaymentGateways,
    service: PaymentCheckoutServiceDep,
) -> PaymentAttemptLookupResponse:
    attempt = await service.resolve_by_reference(session, reference)
    return PaymentAttemptLookupResponse(
        payment_id=attempt.payment_id,
        attempt_id=attempt.id,
        status=attempt.status.value,
    )


@router.get(
    "/{payment_id}/pse/financial-institutions",
    response_model=list[FinancialInstitutionResponse],
    summary="Listar bancos disponibles para pagar por PSE",
)
async def list_pse_financial_institutions(
    payment_id: uuid.UUID,
    session: RequireSelfForPaymentGateways,
    service: PaymentCheckoutServiceDep,
) -> list[FinancialInstitutionResponse]:
    institutions = await service.list_pse_institutions(session, payment_id)
    return [
        FinancialInstitutionResponse(
            financial_institution_code=i.financial_institution_code,
            financial_institution_name=i.financial_institution_name,
        )
        for i in institutions
    ]


@router.get(
    "/{payment_id}/transactions/{attempt_id}",
    response_model=PaymentAttemptResponse,
    summary="Consultar el estado de un intento de cobro (polling)",
)
async def get_transaction_status(
    payment_id: uuid.UUID,
    attempt_id: uuid.UUID,
    session: RequireSelfForPaymentGateways,
    service: PaymentCheckoutServiceDep,
) -> PaymentAttemptResponse:
    attempt = await service.refresh_attempt_status(session, payment_id, attempt_id)
    return _to_attempt_response(attempt)


@router.post(
    "/{payment_id}/payment-sources/card",
    response_model=PaymentSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Guardar una tarjeta como fuente de pago reutilizable (cobro automático)",
)
async def create_card_source(
    payment_id: uuid.UUID,
    body: TokenizeCardSourceRequest,
    session: RequireSelfForPaymentGateways,
    service: PaymentSourceServiceDep,
) -> PaymentSourceResponse:
    source = await service.create_card_source(
        session,
        payment_id,
        body.number,
        body.cvc,
        body.exp_month,
        body.exp_year,
        body.card_holder,
        body.customer_email,
    )
    return _to_source_response(source)


@router.post(
    "/{payment_id}/payment-sources/nequi",
    response_model=PaymentSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Guardar Nequi como fuente de pago reutilizable (cobro automático)",
)
async def create_nequi_source(
    payment_id: uuid.UUID,
    body: TokenizeNequiSourceRequest,
    session: RequireSelfForPaymentGateways,
    service: PaymentSourceServiceDep,
) -> PaymentSourceResponse:
    source = await service.create_nequi_source(
        session, payment_id, body.phone_number, body.customer_email
    )
    return _to_source_response(source)


@router.get(
    "/{payment_id}/payment-sources",
    response_model=list[PaymentSourceResponse],
    summary="Listar mis fuentes de pago guardadas",
)
async def list_payment_sources(
    payment_id: uuid.UUID,
    session: RequireSelfForPaymentGateways,
    service: PaymentSourceServiceDep,
) -> list[PaymentSourceResponse]:
    sources = await service.list_active(session, payment_id)
    return [_to_source_response(source) for source in sources]


@router.delete(
    "/{payment_id}/payment-sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revocar una fuente de pago guardada",
)
async def revoke_payment_source(
    payment_id: uuid.UUID,
    source_id: uuid.UUID,
    session: RequireSelfForPaymentGateways,
    service: PaymentSourceServiceDep,
) -> None:
    await service.revoke(session, payment_id, source_id)


def _to_source_response(source) -> PaymentSourceResponse:
    return PaymentSourceResponse(
        id=source.id,
        type=source.type.value,
        status=source.status.value,
        masked_identifier=source.masked_identifier,
        brand=source.brand,
        is_active=source.is_active,
    )
