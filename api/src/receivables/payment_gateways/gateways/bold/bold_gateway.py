"""Adaptador de Bold: implementa el Protocol de pasarela de cobro de receivables."""

from typing import Any

from core.tools.config_tools import get_or_throw
from receivables.payment_gateways.gateways.base import (
    AcceptanceTokens,
    BancolombiaTransferPaymentMethod,
    BrowserInfo,
    CardPaymentMethod,
    DeviceInfo,
    GatewayFinancialInstitution,
    GatewayPaymentSource,
    GatewayTransaction,
    NequiPaymentMethod,
    PaymentMethodInput,
    PsePaymentMethod,
    RedirectAction,
)
from receivables.payment_gateways.gateways.bold.bold_client import BoldClient
from receivables.payment_gateways.services.payment_gateway_credential_service import (
    DecryptedGatewayCredential,
)
from receivables.payment_gateways.utils.bold_status_mapping import (
    bold_status_to_attempt_status,
)
from receivables.payment_gateways.utils.reference_utils import (
    round_cents_to_whole_currency_cents,
)

_NOT_SUPPORTED = (
    "Bold no soporta fuentes de pago guardadas ni cobro automático -- "
    "verificar supports_saved_payment_sources()/supports_automatic_charge() "
    "antes de llamar a este método."
)


class BoldGateway:
    """Adaptador Bold para `receivables` (deudor -> empresa). A diferencia de Wompi,
    la API de Bold (developers.bold.co/pagos-en-linea/api-de-pagos-en-linea) no tiene
    fuente de pago reutilizable ni cobro automático 3RI, y resuelve PSE/Botón
    Bancolombia/3DS por REDIRECCIÓN (el deudor sale de la app y vuelve por
    `callback_url`), no con un reto embebido como Wompi -- ver `RedirectAction`.

    Contrato de `credentials.values` esperado: `identity_key` (autentica cada llamada,
    header `x-api-key`) y `secret_key` (solo para verificar la firma del webhook),
    ambos en `secrets` (cifrados, ya descifrados aquí) -- Bold no tiene un dato
    público equivalente a la `public_key` de Wompi en este flujo server-to-server."""

    name = "BOLD"

    def __init__(self, credentials: DecryptedGatewayCredential) -> None:
        self._credentials = credentials
        self._client = BoldClient()

    @property
    def _identity_key(self) -> str:
        return self._credentials.get("identity_key") or ""

    @property
    def _secret_key(self) -> str:
        return self._credentials.get("secret_key") or ""

    async def get_acceptance_tokens(self) -> AcceptanceTokens:
        """Bold no tiene el concepto de tokens de aceptación de Wompi -- su página de
        cobro alojada resuelve la aceptación de términos/habeas data por su cuenta.
        Se devuelven vacíos en vez de levantar para que
        `PaymentCheckoutService.create_transaction` no necesite conocer por adelantado
        qué pasarela está activa."""
        return AcceptanceTokens(
            acceptance_token="",
            acceptance_permalink="",
            personal_data_token="",
            personal_data_permalink="",
        )

    async def create_transaction(
        self,
        reference: str,
        amount_in_cents: int,
        currency: str,
        payment_method: PaymentMethodInput | None,
        acceptance_token: str,  # pylint: disable=unused-argument
        accept_personal_auth: str,  # pylint: disable=unused-argument
        customer_email: str,
        payment_source_id: str | None = None,
        browser_info: BrowserInfo | None = None,  # pylint: disable=unused-argument
        device_info: DeviceInfo | None = None,  # pylint: disable=unused-argument
    ) -> GatewayTransaction:
        """`acceptance_token`/`accept_personal_auth` se reciben por simetría con el
        Protocol pero Bold no los usa (ver `get_acceptance_tokens`). `browser_info`
        tampoco aplica: el 3DS de Bold se resuelve por redirección, no con
        fingerprint de navegador en el payload. `device_info` tampoco (lo exige
        PayU, no Bold)."""
        if payment_source_id is not None:
            raise NotImplementedError(_NOT_SUPPORTED)
        if payment_method is None:
            raise ValueError("create_transaction requiere payment_method.")

        rounded_amount_in_cents = round_cents_to_whole_currency_cents(amount_in_cents)
        total_amount = rounded_amount_in_cents // 100
        callback_url = (
            f"{get_or_throw('RECEIVABLES_PAYMENT_REDIRECT_RETURN_URL')}"
            f"?reference={reference}"
        )

        await self._client.create_payment_intent(
            self._identity_key,
            {
                "reference_id": reference,
                "amount": {"currency": currency, "total_amount": total_amount},
                "callback_url": callback_url,
                "customer": {"email": customer_email},
            },
        )

        payment_method_payload = await self._build_payment_method_payload(
            payment_method
        )
        response = await self._client.create_payment(
            self._identity_key,
            {
                "reference_id": reference,
                "payer": {"email": customer_email, **_payer_identity(payment_method)},
                "payment_method": payment_method_payload,
            },
        )
        return self._to_transaction(
            response,
            reference,
            rounded_amount_in_cents,
            currency,
            payment_method_payload["name"],
        )

    async def _build_payment_method_payload(
        self, payment_method: PaymentMethodInput
    ) -> dict[str, Any]:
        if isinstance(payment_method, CardPaymentMethod):
            # shortcut: la doc de Bold documenta un "Billing Address Object"
            # (city/country_code/street/zip_code/state) pero no aclara si va anidado
            # en CREDIT_CARD ni bajo que llave -- la tabla propia de CREDIT_CARD no lo
            # lista como campo. Se omite hasta confirmar contra sandbox real; si Bold
            # lo exige, el pago con tarjeta fallara con un error explicito de Bold, no
            # en silencio.
            return {
                "name": "CREDIT_CARD",
                "card_number": payment_method.number,
                "cvc": payment_method.cvc,
                "cardholder_name": payment_method.card_holder,
                "expiration_month": payment_method.exp_month,
                "expiration_year": payment_method.exp_year,
                "installments": payment_method.installments,
            }
        if isinstance(payment_method, PsePaymentMethod):
            # El esquema `PSE` de creacion de pago documenta `bank_code` como
            # integer (distinto del esquema `BankItem` de
            # `list_pse_financial_institutions`, que lo documenta como string -- la
            # propia doc de Bold es inconsistente entre esos dos esquemas).
            return {
                "name": "PSE",
                "bank_code": int(payment_method.financial_institution_code),
                "bank_name": await self._resolve_bank_name(
                    payment_method.financial_institution_code
                ),
            }
        if isinstance(payment_method, NequiPaymentMethod):
            return {"name": "NEQUI", "phone_number": payment_method.phone_number}
        if isinstance(payment_method, BancolombiaTransferPaymentMethod):
            return {"name": "BOTON_BANCOLOMBIA"}
        raise ValueError(
            f"Metodo de pago no soportado por Bold: {type(payment_method)!r}"
        )

    async def _resolve_bank_name(self, bank_code: str) -> str:
        """`PsePaymentMethod` solo trae el código del banco (Wompi no necesita el
        nombre); Bold sí lo pide en el payload de pago, así que se resuelve contra
        `GET /v1/payment/pse/banks` en vez de agregar un campo nuevo al Protocol
        genérico solo para esto."""
        for bank in await self.list_pse_financial_institutions():
            if bank.financial_institution_code == bank_code:
                return bank.financial_institution_name
        return ""

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
        response = await self._client.list_pse_banks(self._identity_key)
        banks = response.get("data") if isinstance(response, dict) else response
        return [
            GatewayFinancialInstitution(
                financial_institution_code=str(bank.get("bank_code", "")),
                financial_institution_name=bank.get("bank_name", ""),
            )
            for bank in (banks or [])
        ]

    async def get_transaction(self, transaction_id: str) -> GatewayTransaction:
        """`transaction_id` aquí es en realidad NUESTRO `reference` -- el endpoint de
        consulta de Bold (`GET /v1/payment/{reference_id}`) resuelve por el
        `reference_id` que nosotros elegimos, no por el id interno de Bold (ver nota
        en `_to_transaction`)."""
        response = await self._client.get_payment_status(
            self._identity_key, transaction_id
        )
        amount = response.get("amount")
        amount_in_cents = (
            int(amount.get("total_amount", 0)) * 100
            if isinstance(amount, dict)
            else int(amount or 0) * 100
        )
        return GatewayTransaction(
            id=transaction_id,
            status=bold_status_to_attempt_status(response.get("status", "")).value,
            amount_in_cents=amount_in_cents,
            currency=(
                (amount or {}).get("currency", "COP")
                if isinstance(amount, dict)
                else "COP"
            ),
            reference=transaction_id,
            payment_method_type=str(response.get("payment_method", "")),
            raw=response,
        )

    async def confirm_daviplata_otp(
        self, transaction_id: str, id_session_token: str, otp: str
    ) -> GatewayTransaction:
        """Solo ePayco tiene este concepto -- Bold no tiene Daviplata."""
        raise NotImplementedError("Bold no soporta Daviplata.")

    def verify_webhook_signature(
        self, event_body: dict[str, Any]  # pylint: disable=unused-argument
    ) -> bool:
        """La firma de Bold (`x-bold-signature`) se calcula sobre los BYTES crudos del
        body más un header -- a diferencia del checksum de Wompi, no se puede
        reconstruir desde el `dict` ya parseado que exige este método del Protocol.
        `BoldWebhookService` NO usa este método: verifica directamente con
        `verify_bold_webhook_signature` (ver `gateways/bold/bold_signature.py`) sobre
        el body crudo y el header, antes de parsear el JSON. Este método existe solo
        para cumplir el Protocol -- levanta en vez de devolver `False`, para que un
        llamador que lo invoque por error no reciba un "firma inválida" silenciosamente
        incorrecto."""
        raise NotImplementedError(
            "BoldGateway no verifica la firma del webhook por este método -- "
            "usar verify_bold_webhook_signature sobre el body crudo."
        )

    def supports_automatic_charge(self) -> bool:
        return False

    def supports_saved_payment_sources(self) -> bool:
        return False

    def _to_transaction(
        self,
        response: dict[str, Any],
        reference: str,
        amount_in_cents: int,
        currency: str,
        payment_method_type: str,
    ) -> GatewayTransaction:
        next_actions = response.get("next_actions") or {}
        redirect_url = next_actions.get("redirect_url")
        redirect_action = (
            RedirectAction(
                redirect_url=redirect_url,
                redirect_method=next_actions.get("redirect_method", "GET"),
            )
            if redirect_url
            else None
        )
        # `id` se puebla con NUESTRO `reference`, no con el `transaction_id` interno
        # de Bold -- `get_transaction` consulta por `reference_id` (ver su docstring),
        # y el resto del módulo (polling, webhook) siempre reconsulta por el valor
        # guardado en `provider_transaction_id`/`GatewayTransaction.id`.
        return GatewayTransaction(
            id=reference,
            status=bold_status_to_attempt_status(response.get("status", "")).value,
            amount_in_cents=amount_in_cents,
            currency=currency,
            reference=reference,
            payment_method_type=payment_method_type,
            raw=response,
            redirect_action=redirect_action,
        )


def _payer_identity(payment_method: PaymentMethodInput) -> dict[str, str]:
    """Bold pide identificación del pagador (`payer.document_type`/`document_number`)
    -- solo `PsePaymentMethod` la trae en nuestro modelo genérico (Wompi la pide dentro
    del propio método PSE, no del payer). Para tarjeta/Nequi/Bancolombia se manda sin
    documento: a confirmar contra el sandbox de Bold si lo exige también ahí."""
    if isinstance(payment_method, PsePaymentMethod):
        return {
            "document_type": payment_method.user_legal_id_type,
            "document_number": payment_method.user_legal_id,
        }
    return {}
