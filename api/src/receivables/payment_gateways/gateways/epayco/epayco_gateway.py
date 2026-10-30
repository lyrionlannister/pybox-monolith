"""Adaptador de ePayco Latam: implementa el Protocol de pasarela de cobro de
receivables."""

from decimal import Decimal
from typing import Any

from core.tools.config_tools import get_or_throw
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ReceivablesPaymentAttemptStatus,
)
from receivables.payment_gateways.gateways.base import (
    AcceptanceTokens,
    BrowserInfo,
    DaviplataPaymentMethod,
    DeviceInfo,
    GatewayFinancialInstitution,
    GatewayPaymentSource,
    GatewayTransaction,
    OtpChallenge,
    PaymentMethodInput,
    PsePaymentMethod,
    RedirectAction,
)
from receivables.payment_gateways.gateways.epayco.epayco_client import EpaycoClient
from receivables.payment_gateways.gateways.epayco.epayco_signature import (
    verify_epayco_confirmation_signature,
)
from receivables.payment_gateways.services.payment_gateway_credential_service import (
    DecryptedGatewayCredential,
)
from receivables.payment_gateways.utils.epayco_status_mapping import (
    epayco_status_to_attempt_status,
)
from receivables.payment_gateways.utils.reference_utils import (
    round_cents_to_whole_currency_cents,
)

_NOT_SUPPORTED = (
    "ePayco solo soporta PSE y Daviplata en esta integracion -- tarjeta, fuentes de "
    "pago guardadas y cobro automatico no estan implementados (ver docstring de "
    "EpaycoGateway)."
)


class EpaycoGateway:
    """Adaptador ePayco para `receivables` (deudor -> empresa). Alcance acordado al
    agregar este adaptador: PSE y Daviplata -- tarjeta queda sin implementar (su 3D
    Secure vía API es opt-in por cuenta y exige un script propio de ePayco distinto al
    de Wompi, docs.epayco.com/docs/technical-documentation-template) y ePayco no tiene
    Nequi ni Botón Bancolombia.

    Daviplata es el único método de este Protocol que no se resuelve ni por
    redirección ni por notificación push esperada en silencio: ePayco devuelve un OTP
    al celular del deudor que hay que volver a pedirle en el formulario y confirmar
    con una segunda llamada (`confirm_daviplata_otp`, ver `OtpChallenge`) -- por eso es
    el único método nuevo que esta integración agrega al Protocol común.

    A diferencia de Bold/Wompi/PayU, ePayco exige un login previo (Basic auth con
    `public_key`/`private_key`) que devuelve un JWT de corta duración -- se pide de
    nuevo en cada llamada pública de este adaptador (sin cachear) en vez de guardarlo
    en la instancia, mismo criterio de simplicidad que el resto de los adaptadores de
    este módulo (ninguno cachea tokens entre llamadas).

    El ambiente (sandbox/producción) NO determina el host (una sola base URL, ver
    `EpaycoClient`) ni la llave -- se manda explícito como `testMode` en cada payload,
    a diferencia de PayU.

    Contrato de `credentials.values` esperado: `private_key` (login contra la Apify,
    junto con `public_key`, ver `EpaycoClient.login`) y `p_key` (firma de la
    confirmación, junto con `p_cust_id_cliente`) en `secrets`; `public_key`,
    `p_cust_id_cliente` y `environment` (`"sandbox"`/`"production"`) en
    `public_config`."""

    name = "EPAYCO"

    def __init__(self, credentials: DecryptedGatewayCredential) -> None:
        self._credentials = credentials
        self._client = EpaycoClient()

    @property
    def _public_key(self) -> str:
        return self._credentials.get("public_key") or ""

    @property
    def _private_key(self) -> str:
        return self._credentials.get("private_key") or ""

    @property
    def _customer_id(self) -> str:
        return self._credentials.get("p_cust_id_cliente") or ""

    @property
    def _p_key(self) -> str:
        return self._credentials.get("p_key") or ""

    @property
    def _is_test(self) -> bool:
        return (self._credentials.get("environment") or "sandbox") != "production"

    async def _login(self) -> str:
        """`bearer_token` es el campo primario de la respuesta de `/login` (confirmado
        contra los SDKs oficiales de Go y Ruby de ePayco); `token` es el fallback que
        usan ambos SDKs cuando el primero viene vacío. Antes solo se leia `token` --
        si la API real nombra el campo `bearer_token`, cada llamada quedaba
        autenticando con un token vacio (401 persistente sin error en el origen)."""
        response = await self._client.login(self._public_key, self._private_key)
        return str(response.get("bearer_token") or response.get("token", ""))

    async def get_acceptance_tokens(self) -> AcceptanceTokens:
        """ePayco no tiene el concepto de tokens de aceptación de Wompi -- mismo
        criterio que `BoldGateway`/`PayUGateway.get_acceptance_tokens`."""
        return AcceptanceTokens(
            acceptance_token="",
            acceptance_permalink="",
            personal_data_token="",
            personal_data_permalink="",
        )

    async def create_transaction(
        self,
        reference: str,  # pylint: disable=unused-argument
        amount_in_cents: int,
        currency: str,  # pylint: disable=unused-argument
        payment_method: PaymentMethodInput | None,
        acceptance_token: str,  # pylint: disable=unused-argument
        accept_personal_auth: str,  # pylint: disable=unused-argument
        customer_email: str,
        payment_source_id: str | None = None,
        browser_info: BrowserInfo | None = None,  # pylint: disable=unused-argument
        device_info: DeviceInfo | None = None,
    ) -> GatewayTransaction:
        """PSE/Daviplata -- ver `_NOT_SUPPORTED`. `reference`/`currency` se reciben por
        simetría con el Protocol pero ePayco no los usa: no acepta una referencia
        propia en la creación (solo genera la suya, `ref_payco`) y solo soporta COP.
        `device_info` solo se usa para `ip_address` (exigido por ePayco) -- a
        diferencia de PayU, no hace falta `device_session_id`/`cookie`/`user_agent`."""
        if payment_source_id is not None:
            raise NotImplementedError(_NOT_SUPPORTED)
        ip_address = device_info.ip_address if device_info else ""
        if isinstance(payment_method, PsePaymentMethod):
            return await self._create_pse_transaction(
                amount_in_cents, payment_method, customer_email, ip_address
            )
        if isinstance(payment_method, DaviplataPaymentMethod):
            return await self._create_daviplata_transaction(
                amount_in_cents, payment_method, customer_email, ip_address
            )
        raise NotImplementedError(_NOT_SUPPORTED)

    async def _create_pse_transaction(
        self,
        amount_in_cents: int,
        payment_method: PsePaymentMethod,
        customer_email: str,
        ip_address: str,
    ) -> GatewayTransaction:
        if not all(
            [
                payment_method.full_name,
                payment_method.phone,
                payment_method.address,
                payment_method.user_legal_id,
            ]
        ):
            raise ValueError(
                "ePayco (PSE) requiere nombre completo, teléfono, dirección y "
                "documento del pagador."
            )
        name, last_name = _split_full_name(payment_method.full_name or "")
        rounded_amount_in_cents = round_cents_to_whole_currency_cents(amount_in_cents)
        token = await self._login()
        payload = {
            "bank": payment_method.financial_institution_code,
            "value": str(rounded_amount_in_cents // 100),
            "docType": payment_method.user_legal_id_type,
            "docNumber": payment_method.user_legal_id,
            "name": name,
            "lastName": last_name,
            "email": customer_email,
            # ePayco pide celular y teléfono fijo como campos separados -- el
            # formulario del frontend solo pide un teléfono (igual para las demás
            # pasarelas), así que se manda el mismo valor en los dos.
            "cellPhone": payment_method.phone,
            "phone": payment_method.phone,
            "address": payment_method.address,
            "city": payment_method.city or "",
            "ip": ip_address,
            "description": payment_method.payment_description,
            "urlResponse": self._build_response_url(),
            "urlConfirmation": self._build_notify_url(),
            "methodConfirmation": "POST",
            "testMode": self._is_test,
        }
        response = await self._client.create_pse_transaction(token, payload)
        data = response.get("data") or {}
        bank_url = data.get("urlbanco") or None
        redirect_action = (
            RedirectAction(redirect_url=bank_url, redirect_method="GET")
            if bank_url
            else None
        )
        reference_payco = str(data.get("ref_payco", ""))
        return GatewayTransaction(
            id=reference_payco,
            status=epayco_status_to_attempt_status(data.get("estado", "")).value,
            amount_in_cents=rounded_amount_in_cents,
            currency="COP",
            reference=reference_payco,
            payment_method_type="PSE",
            raw=response,
            redirect_action=redirect_action,
        )

    async def _create_daviplata_transaction(
        self,
        amount_in_cents: int,
        payment_method: DaviplataPaymentMethod,
        customer_email: str,
        ip_address: str,
    ) -> GatewayTransaction:
        if not all(
            [
                payment_method.full_name,
                payment_method.address,
                payment_method.city,
                payment_method.user_legal_id,
            ]
        ):
            raise ValueError(
                "ePayco (Daviplata) requiere nombre completo, dirección, ciudad y "
                "documento del pagador."
            )
        name, last_name = _split_full_name(payment_method.full_name)
        rounded_amount_in_cents = round_cents_to_whole_currency_cents(amount_in_cents)
        token = await self._login()
        payload = {
            "docType": payment_method.user_legal_id_type,
            "document": payment_method.user_legal_id,
            "name": name,
            "lastName": last_name,
            "email": customer_email,
            "indCountry": "CO",
            "phone": payment_method.phone or "",
            "country": "CO",
            "city": payment_method.city,
            "address": payment_method.address,
            "ip": ip_address,
            "value": str(rounded_amount_in_cents // 100),
            "urlConfirmation": self._build_notify_url(),
            "methodConfirmation": "POST",
            "testMode": self._is_test,
        }
        response = await self._client.create_daviplata_transaction(token, payload)
        data = (response.get("data") or {}).get("transaction") or {}
        reference_payco = str(data.get("refPayco", ""))
        id_session_token = str(data.get("idSessionToken") or "")
        otp_challenge = (
            OtpChallenge(
                transaction_id=reference_payco, id_session_token=id_session_token
            )
            if id_session_token
            else None
        )
        return GatewayTransaction(
            id=reference_payco,
            status=epayco_status_to_attempt_status(data.get("estatus", "")).value,
            amount_in_cents=rounded_amount_in_cents,
            currency="COP",
            reference=reference_payco,
            payment_method_type="DAVIPLATA",
            raw=response,
            otp_challenge=otp_challenge,
        )

    async def confirm_daviplata_otp(
        self, transaction_id: str, id_session_token: str, otp: str
    ) -> GatewayTransaction:
        token = await self._login()
        payload = {
            "refPayco": transaction_id,
            "idSessionToken": id_session_token,
            "otp": otp,
        }
        response = await self._client.confirm_daviplata_transaction(token, payload)
        data = response.get("data") or {}
        amount_in_cents = int(Decimal(str(data.get("value", 0))) * 100)
        return GatewayTransaction(
            id=transaction_id,
            status=epayco_status_to_attempt_status(data.get("status", "")).value,
            amount_in_cents=amount_in_cents,
            currency="COP",
            reference=transaction_id,
            payment_method_type="DAVIPLATA",
            raw=response,
        )

    def _build_response_url(self) -> str:
        """Sin query string propio: ePayco redirige a esta URL agregando
        `?ref_payco=<su propio id>` (docs.epayco.com/docs/checkout-respuesta-y-
        confirmacion) -- no hay forma documentada de garantizar que preserve un
        `?reference=...` nuestro. `PaymentCheckoutService.resolve_by_reference`
        resuelve este caso buscando por `provider_transaction_id` cuando no encuentra
        la referencia propia (ver también `usePaymentRedirectReturn` en el frontend)."""
        return get_or_throw("RECEIVABLES_PAYMENT_REDIRECT_RETURN_URL")

    def _build_notify_url(self) -> str:
        return (
            f"{get_or_throw('RECEIVABLES_EPAYCO_NOTIFY_URL')}"
            f"/{self._credentials.organization_id}"
        )

    async def tokenize_card(
        self, number: str, cvc: str, exp_month: str, exp_year: str, card_holder: str
    ) -> str:
        raise NotImplementedError(_NOT_SUPPORTED)

    async def tokenize_nequi(self, phone_number: str) -> str:
        raise NotImplementedError(_NOT_SUPPORTED)

    async def create_payment_source(
        self,
        type: str,
        token: str,
        customer_email: str,
        acceptance_token: str,
        accept_personal_auth: str,
    ) -> GatewayPaymentSource:
        raise NotImplementedError(_NOT_SUPPORTED)

    async def list_pse_financial_institutions(
        self,
    ) -> list[GatewayFinancialInstitution]:
        token = await self._login()
        response = await self._client.get_pse_banks(token)
        banks = response.get("data") or []
        return [
            GatewayFinancialInstitution(
                financial_institution_code=str(bank.get("bankCode", "")),
                financial_institution_name=bank.get("bankName", ""),
            )
            for bank in banks
            # ePayco incluye un placeholder ("0", "A continuación seleccione su
            # banco") en el mismo listado -- no es un banco real.
            if str(bank.get("bankCode", "")) != "0"
        ]

    async def get_transaction(self, transaction_id: str) -> GatewayTransaction:
        """`transaction_id` aquí es el `ref_payco` que ePayco generó (ver
        `_create_pse_transaction`/`_create_daviplata_transaction`) -- ePayco no acepta
        buscar por una referencia propia nuestra en este endpoint."""
        token = await self._login()
        payload = {"filter": {"referencePayco": transaction_id}}
        response = await self._client.get_transaction_detail(token, payload)
        if not response.get("success"):
            # ePayco todavia no tiene esta transaccion (el deudor aun no vuelve del
            # banco, o el OTP de Daviplata aun no se confirma) -- igual que
            # `NO_TRANSACTION_FOUND` de Bold/PayU, se trata como pendiente para que el
            # polling siga reintentando.
            return GatewayTransaction(
                id=transaction_id,
                status=ReceivablesPaymentAttemptStatus.PENDING.value,
                amount_in_cents=0,
                currency="COP",
                reference=transaction_id,
                payment_method_type="",
                raw=response,
            )
        data = response.get("data") or {}
        amount_in_cents = int(Decimal(str(data.get("amount", 0))) * 100)
        return GatewayTransaction(
            id=transaction_id,
            status=epayco_status_to_attempt_status(data.get("status", "")).value,
            amount_in_cents=amount_in_cents,
            currency=data.get("currency", "COP"),
            reference=transaction_id,
            payment_method_type=str(data.get("paymentMethod", "")),
            raw=response,
        )

    def verify_webhook_signature(self, event_body: dict[str, Any]) -> bool:
        """La confirmación de ePayco llega como POST con los campos ya planos -- se
        puede verificar directamente sobre el `dict` ya parseado, como Wompi/PayU."""
        fields = {str(k): str(v) for k, v in event_body.items()}
        return verify_epayco_confirmation_signature(
            fields, self._customer_id, self._p_key
        )

    def supports_automatic_charge(self) -> bool:
        return False

    def supports_saved_payment_sources(self) -> bool:
        return False


def _split_full_name(full_name: str) -> tuple[str, str]:
    """ePayco exige `name`/`lastName` separados -- el formulario del frontend solo
    pide un "Nombre completo" (igual para las demás pasarelas, ver `PsePaymentMethod`),
    así que se parte por el primer espacio. Heurística, no hay forma confiable de
    separar nombre/apellido de un string libre -- documentado como simplificación
    conocida."""
    parts = full_name.strip().split(" ", 1)
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], parts[1]
