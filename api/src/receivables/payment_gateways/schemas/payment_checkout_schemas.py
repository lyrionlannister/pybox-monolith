"""Schemas de checkout: métodos de pago y transacciones contra la pasarela."""

import uuid
from typing import Annotated, Literal, Union

from pydantic import EmailStr, Field

from core.base.schema_base import BaseSchema


class BrowserInfoRequest(BaseSchema):
    """Fingerprint del navegador del deudor, exigido por Wompi para 3D Secure v2 en
    pagos con tarjeta (ver skill `wompi-gateway`, Paso 6)."""

    browser_color_depth: str
    browser_screen_height: str
    browser_screen_width: str
    browser_language: str
    browser_user_agent: str
    browser_tz: str


class DeviceInfoRequest(BaseSchema):
    """Antifraude exigido por PayU (ver `DeviceInfo`). La IP no viaja aquí: el backend
    la toma de la petición, nunca del cliente."""

    device_session_id: str
    cookie: str
    user_agent: str


class CardTransactionRequest(BaseSchema):
    payment_method_type: Literal["CARD"] = "CARD"
    number: str
    cvc: str
    exp_month: str
    exp_year: str
    card_holder: str
    installments: int = Field(default=1, ge=1)
    customer_email: EmailStr
    browser_info: BrowserInfoRequest


class PseTransactionRequest(BaseSchema):
    payment_method_type: Literal["PSE"] = "PSE"
    user_type: int = Field(description="0 = persona natural, 1 = persona jurídica")
    user_legal_id_type: str
    user_legal_id: str
    financial_institution_code: str
    payment_description: str
    customer_email: EmailStr
    device_info: DeviceInfoRequest | None = None


class NequiTransactionRequest(BaseSchema):
    """`full_name`/`user_legal_id_type`/`user_legal_id`/`address`/`city` son
    ignorados por Wompi (solo pide `phone_number`) pero obligatorios para PayU, que
    exige `buyer`/`payer` completos -- ver `PayUGateway`."""

    payment_method_type: Literal["NEQUI"] = "NEQUI"
    phone_number: str
    customer_email: EmailStr
    full_name: str | None = None
    user_legal_id_type: str | None = None
    user_legal_id: str | None = None
    address: str | None = None
    city: str | None = None
    device_info: DeviceInfoRequest | None = None


class BancolombiaTransferTransactionRequest(BaseSchema):
    """Mismos campos opcionales del pagador que `NequiTransactionRequest`: Wompi/Bold
    los ignoran, PayU los exige."""

    payment_method_type: Literal["BANCOLOMBIA_TRANSFER"] = "BANCOLOMBIA_TRANSFER"
    payment_description: str
    customer_email: EmailStr
    full_name: str | None = None
    user_legal_id_type: str | None = None
    user_legal_id: str | None = None
    address: str | None = None
    city: str | None = None
    device_info: DeviceInfoRequest | None = None


class DaviplataTransactionRequest(BaseSchema):
    """Solo ePayco. El cobro queda `PENDING` hasta confirmar el OTP que llega a la app
    Daviplata del deudor (ver `DaviplataOtpConfirmRequest`)."""

    payment_method_type: Literal["DAVIPLATA"] = "DAVIPLATA"
    customer_email: EmailStr
    full_name: str
    user_legal_id_type: str
    user_legal_id: str
    address: str
    city: str
    phone: str | None = None
    device_info: DeviceInfoRequest | None = None


class DaviplataOtpConfirmRequest(BaseSchema):
    otp: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")


TransactionRequest = Annotated[
    Union[
        CardTransactionRequest,
        PseTransactionRequest,
        NequiTransactionRequest,
        BancolombiaTransferTransactionRequest,
        DaviplataTransactionRequest,
    ],
    Field(discriminator="payment_method_type"),
]


class PaymentAttemptResponse(BaseSchema):
    id: uuid.UUID
    status: str
    provider_reference: str | None
    provider_transaction_id: str | None
    charge_mode: str


class ThreeDsChallengeResponse(BaseSchema):
    current_step: str
    current_step_status: str
    challenge_html: str


class RedirectActionResponse(BaseSchema):
    """El deudor debe navegar a `redirect_url` para confirmar el cobro (PSE, Botón
    Bancolombia o 3DS vía Bold) y vuelve a la app por el `callback_url` configurado --
    a diferencia del reto 3DS de Wompi (`ThreeDsChallengeResponse`), que no sale de la
    pantalla actual."""

    redirect_url: str
    redirect_method: str


class TransactionCreationResponse(BaseSchema):
    attempt: PaymentAttemptResponse
    three_ds_challenge: ThreeDsChallengeResponse | None = None
    redirect_action: RedirectActionResponse | None = None
    otp_required: bool = False


class TokenizeCardSourceRequest(BaseSchema):
    number: str
    cvc: str
    exp_month: str
    exp_year: str
    card_holder: str
    customer_email: EmailStr


class TokenizeNequiSourceRequest(BaseSchema):
    phone_number: str
    customer_email: EmailStr


class PaymentSourceResponse(BaseSchema):
    id: uuid.UUID
    type: str
    status: str
    masked_identifier: str | None
    brand: str | None
    is_active: bool


class FinancialInstitutionResponse(BaseSchema):
    financial_institution_code: str
    financial_institution_name: str


class PaymentAttemptLookupResponse(BaseSchema):
    """Para la página de retorno de una redirección (Bold) -- el frontend solo
    conoce `reference` y necesita `payment_id`/`attempt_id` para retomar el polling
    habitual de `PaymentAttemptResponse`."""

    payment_id: uuid.UUID
    attempt_id: uuid.UUID
    status: str
