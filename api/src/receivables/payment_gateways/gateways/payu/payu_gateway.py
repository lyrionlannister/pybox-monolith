"""Adaptador de PayU Latam: implementa el Protocol de pasarela de cobro de
receivables."""

from decimal import Decimal
from typing import Any

from core.tools.config_tools import get_or_throw
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ReceivablesPaymentAttemptStatus,
)
from receivables.payment_gateways.gateways.base import (
    AcceptanceTokens,
    BancolombiaTransferPaymentMethod,
    BrowserInfo,
    DeviceInfo,
    GatewayFinancialInstitution,
    GatewayPaymentSource,
    GatewayTransaction,
    NequiPaymentMethod,
    PaymentMethodInput,
    PsePaymentMethod,
    RedirectAction,
)
from receivables.payment_gateways.gateways.payu.payu_client import PayUClient
from receivables.payment_gateways.gateways.payu.payu_signature import (
    build_payu_request_signature,
    verify_payu_confirmation_signature,
)
from receivables.payment_gateways.services.payment_gateway_credential_service import (
    DecryptedGatewayCredential,
)
from receivables.payment_gateways.utils.payu_status_mapping import (
    payu_transaction_state_to_attempt_status,
)
from receivables.payment_gateways.utils.reference_utils import (
    round_cents_to_whole_currency_cents,
)

_NOT_SUPPORTED = (
    "PayU solo soporta PSE, NEQUI y BANCOLOMBIA_BUTTON en esta integracion -- "
    "tarjeta, fuentes de pago guardadas y cobro automatico no estan implementados "
    "(ver docstring de PayUGateway)."
)


class PayUGateway:
    """Adaptador PayU Latam para `receivables` (deudor -> empresa). Soporta PSE, NEQUI
    y BANCOLOMBIA_BUTTON -- tarjeta queda sin implementar (decisión registrada al
    agregar este adaptador): en la API de PayU exige el documento de identidad del
    pagador (`payer.dniType`/`dniNumber`) igual que los otros tres métodos, pero el
    formulario de tarjeta del frontend no pide documento (Wompi/Bold no lo necesitan
    para CARD) y no se justificó agregarlo solo para esto.

    PSE y BANCOLOMBIA_BUTTON se resuelven por REDIRECCIÓN (`extraParameters.BANK_URL`
    en la respuesta síncrona de `SUBMIT_TRANSACTION`, ver `RedirectAction`) -- igual
    que Bold. NEQUI es asíncrono por notificación push (sin `BANK_URL`): el deudor
    confirma desde su app y el estado queda `PENDING` hasta la confirmación por
    `notifyUrl` o el polling de `get_transaction`.

    Los tres métodos exigen `buyer`/`payer` completos (nombre, teléfono, documento,
    dirección -- developers.payulatam.com/.../payments-api-colombia.html), por eso
    `PsePaymentMethod`/`NequiPaymentMethod`/`BancolombiaTransferPaymentMethod` se
    extendieron con esos campos opcionales (Wompi/Bold los ignoran). También exigen
    cuatro campos antifraude a nivel de `transaction` (`deviceSessionId`/`ipAddress`/
    `cookie`/`userAgent`, ver `DeviceInfo`) que ninguna otra pasarela pide.

    Contrato de `credentials.values` esperado: `api_key`/`api_login` (autentican cada
    llamada, van en `merchant` del body) en `secrets`; `merchant_id`/`account_id`
    (identifican la cuenta, PayU los expone en su panel) y `environment`
    (`"sandbox"`/`"production"`, determina el host) en `public_config`."""

    name = "PAYU"

    def __init__(self, credentials: DecryptedGatewayCredential) -> None:
        self._credentials = credentials
        self._client = PayUClient()

    @property
    def _api_key(self) -> str:
        return self._credentials.get("api_key") or ""

    @property
    def _api_login(self) -> str:
        return self._credentials.get("api_login") or ""

    @property
    def _merchant_id(self) -> str:
        return self._credentials.get("merchant_id") or ""

    @property
    def _account_id(self) -> str:
        return self._credentials.get("account_id") or ""

    @property
    def _environment(self) -> str:
        return self._credentials.get("environment") or "sandbox"

    @property
    def _is_test(self) -> bool:
        return self._environment != "production"

    async def get_acceptance_tokens(self) -> AcceptanceTokens:
        """PayU no tiene el concepto de tokens de aceptación de Wompi -- en integración
        directa a su API no hay una pantalla propia que resuelva la aceptación de
        términos/habeas data por su cuenta. Vacíos, mismo criterio que
        `BoldGateway.get_acceptance_tokens`."""
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
        device_info: DeviceInfo | None = None,
    ) -> GatewayTransaction:
        """PSE/NEQUI/BANCOLOMBIA_BUTTON -- ver `_NOT_SUPPORTED`. `acceptance_token`/
        `accept_personal_auth`/`browser_info` se reciben por simetría con el Protocol
        pero PayU no los usa. `device_info` sí lo exige PayU para los tres (antifraude,
        ver `DeviceInfo`) -- a diferencia de `browser_info`, no es opcional aquí. El
        controller SIEMPRE construye un `DeviceInfo` (lo necesita también ePayco, solo
        para `ip_address`), así que aquí se valida cada campo propio de PayU en vez de
        solo `is None`."""
        if payment_source_id is not None:
            raise NotImplementedError(_NOT_SUPPORTED)
        if device_info is None or not all(
            [device_info.device_session_id, device_info.cookie, device_info.user_agent]
        ):
            raise ValueError(
                "PayU requiere device_info (antifraude) para cualquier cobro."
            )
        if isinstance(payment_method, PsePaymentMethod):
            return await self._create_pse_transaction(
                reference,
                amount_in_cents,
                currency,
                payment_method,
                customer_email,
                device_info,
            )
        if isinstance(payment_method, NequiPaymentMethod):
            return await self._create_nequi_transaction(
                reference,
                amount_in_cents,
                currency,
                payment_method,
                customer_email,
                device_info,
            )
        if isinstance(payment_method, BancolombiaTransferPaymentMethod):
            return await self._create_bancolombia_transaction(
                reference,
                amount_in_cents,
                currency,
                payment_method,
                customer_email,
                device_info,
            )
        raise NotImplementedError(_NOT_SUPPORTED)

    async def _create_pse_transaction(
        self,
        reference: str,
        amount_in_cents: int,
        currency: str,
        payment_method: PsePaymentMethod,
        customer_email: str,
        device_info: DeviceInfo,
    ) -> GatewayTransaction:
        self._validate_payer_fields(
            payment_method.full_name,
            payment_method.phone,
            payment_method.user_legal_id,
            payment_method.address,
            payment_method.city,
        )
        amount_in_cents = round_cents_to_whole_currency_cents(amount_in_cents)
        address = self._build_address(payment_method.address, payment_method.city)
        order_extra = {
            "order": {
                "description": payment_method.payment_description,
                "buyer": self._build_buyer(
                    payment_method.full_name,
                    customer_email,
                    payment_method.phone,
                    payment_method.user_legal_id,
                    address,
                ),
            },
            "payer": self._build_payer(
                payment_method.full_name,
                customer_email,
                payment_method.phone,
                payment_method.user_legal_id,
                payment_method.user_legal_id_type,
                address,
            ),
            "extraParameters": {
                "RESPONSE_URL": self._build_response_url(reference),
                # shortcut: la doc de PayU no define PSE_REFERENCE1 en la seccion de
                # PSE (solo PSE_REFERENCE2/3, documento del pagador); el UNICO ejemplo
                # de request que lo muestra manda una IP, no una referencia de
                # negocio. "Confirmation URL" lo describe aparte como "custom
                # reference field 1", sin forzar un formato -- se asume de negocio
                # (nuestra referencia) hasta confirmar contra sandbox real cual de
                # las dos lecturas es la correcta.
                "PSE_REFERENCE1": reference,
                "FINANCIAL_INSTITUTION_CODE": (
                    payment_method.financial_institution_code
                ),
                "USER_TYPE": "J" if payment_method.user_type == 1 else "N",
                "PSE_REFERENCE2": payment_method.user_legal_id_type,
                "PSE_REFERENCE3": payment_method.user_legal_id,
            },
            "paymentMethod": "PSE",
        }
        response = await self._submit_transaction(
            reference, amount_in_cents, currency, order_extra, device_info
        )
        return self._to_transaction(
            response, reference, amount_in_cents, currency, "PSE"
        )

    async def _create_nequi_transaction(
        self,
        reference: str,
        amount_in_cents: int,
        currency: str,
        payment_method: NequiPaymentMethod,
        customer_email: str,
        device_info: DeviceInfo,
    ) -> GatewayTransaction:
        self._validate_payer_fields(
            payment_method.full_name,
            payment_method.phone_number,
            payment_method.user_legal_id,
            payment_method.address,
            payment_method.city,
        )
        amount_in_cents = round_cents_to_whole_currency_cents(amount_in_cents)
        address = self._build_address(payment_method.address, payment_method.city)
        order_extra = {
            "order": {
                "description": payment_method.payment_description or reference,
                "buyer": self._build_buyer(
                    payment_method.full_name,
                    customer_email,
                    payment_method.phone_number,
                    payment_method.user_legal_id,
                    address,
                ),
            },
            "payer": self._build_payer(
                payment_method.full_name,
                customer_email,
                payment_method.phone_number,
                payment_method.user_legal_id,
                payment_method.user_legal_id_type,
                address,
            ),
            "extraParameters": {},
            "paymentMethod": "NEQUI",
        }
        response = await self._submit_transaction(
            reference, amount_in_cents, currency, order_extra, device_info
        )
        return self._to_transaction(
            response, reference, amount_in_cents, currency, "NEQUI"
        )

    async def _create_bancolombia_transaction(
        self,
        reference: str,
        amount_in_cents: int,
        currency: str,
        payment_method: BancolombiaTransferPaymentMethod,
        customer_email: str,
        device_info: DeviceInfo,
    ) -> GatewayTransaction:
        self._validate_payer_fields(
            payment_method.full_name,
            payment_method.phone,
            payment_method.user_legal_id,
            payment_method.address,
            payment_method.city,
        )
        amount_in_cents = round_cents_to_whole_currency_cents(amount_in_cents)
        address = self._build_address(payment_method.address, payment_method.city)
        order_extra = {
            "order": {
                "description": payment_method.payment_description,
                "buyer": self._build_buyer(
                    payment_method.full_name,
                    customer_email,
                    payment_method.phone,
                    payment_method.user_legal_id,
                    address,
                ),
            },
            "payer": self._build_payer(
                payment_method.full_name,
                customer_email,
                payment_method.phone,
                payment_method.user_legal_id,
                payment_method.user_legal_id_type,
                address,
            ),
            "extraParameters": {},
            "paymentMethod": "BANCOLOMBIA_BUTTON",
        }
        response = await self._submit_transaction(
            reference, amount_in_cents, currency, order_extra, device_info
        )
        return self._to_transaction(
            response, reference, amount_in_cents, currency, "BANCOLOMBIA_BUTTON"
        )

    async def _submit_transaction(
        self,
        reference: str,
        amount_in_cents: int,
        currency: str,
        order_extra: dict[str, Any],
        device_info: DeviceInfo,
    ) -> dict[str, Any]:
        """Partes comunes del payload de `SUBMIT_TRANSACTION` a los tres métodos
        soportados -- `order_extra` trae lo que cambia por método (`description`/
        `buyer` de la orden, `payer`, `extraParameters`, `paymentMethod`)."""
        amount = amount_in_cents // 100
        signature = build_payu_request_signature(
            self._api_key, self._merchant_id, reference, amount_in_cents, currency
        )
        payload = {
            "test": self._is_test,
            "language": "es",
            "command": "SUBMIT_TRANSACTION",
            "merchant": {"apiLogin": self._api_login, "apiKey": self._api_key},
            "transaction": {
                "order": {
                    "accountId": self._account_id,
                    "referenceCode": reference,
                    "language": "es",
                    "signature": signature,
                    "notifyUrl": self._build_notify_url(),
                    "additionalValues": {
                        "TX_VALUE": {"value": amount, "currency": currency}
                    },
                    **order_extra["order"],
                },
                "payer": order_extra["payer"],
                "extraParameters": order_extra["extraParameters"],
                "type": "AUTHORIZATION_AND_CAPTURE",
                "paymentMethod": order_extra["paymentMethod"],
                "paymentCountry": "CO",
                "deviceSessionId": device_info.device_session_id,
                "ipAddress": device_info.ip_address,
                "cookie": device_info.cookie,
                "userAgent": device_info.user_agent,
            },
        }
        return await self._client.submit_transaction(self._environment, payload)

    @staticmethod
    def _validate_payer_fields(
        full_name: str | None,
        phone: str | None,
        user_legal_id: str | None,
        address: str | None,
        city: str | None,
    ) -> None:
        if not all([full_name, phone, user_legal_id, address, city]):
            raise ValueError(
                "PayU requiere nombre completo, teléfono, documento, dirección y "
                "ciudad del pagador."
            )

    @staticmethod
    def _build_address(address: str | None, city: str | None) -> dict[str, str]:
        return {"street1": address or "", "city": city or "", "country": "CO"}

    @staticmethod
    def _build_buyer(
        full_name: str | None,
        customer_email: str,
        phone: str | None,
        user_legal_id: str | None,
        address: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "fullName": full_name,
            "emailAddress": customer_email,
            "contactPhone": phone,
            "dniNumber": user_legal_id,
            "shippingAddress": address,
        }

    @staticmethod
    def _build_payer(
        full_name: str | None,
        customer_email: str,
        phone: str | None,
        user_legal_id: str | None,
        user_legal_id_type: str | None,
        address: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "fullName": full_name,
            "emailAddress": customer_email,
            "contactPhone": phone,
            "dniNumber": user_legal_id,
            "dniType": user_legal_id_type,
            "billingAddress": address,
        }

    def _build_response_url(self, reference: str) -> str:
        return (
            f"{get_or_throw('RECEIVABLES_PAYMENT_REDIRECT_RETURN_URL')}"
            f"?reference={reference}"
        )

    def _build_notify_url(self) -> str:
        """Confirmación server-to-server (PayU llama directo a esta API, a diferencia
        de `RESPONSE_URL`, que abre el navegador del deudor) -- mismo patrón de tenant
        por URL que `/webhooks/bold/{organization_id}` (ver `PayUWebhookService`)."""
        return (
            f"{get_or_throw('RECEIVABLES_PAYU_NOTIFY_URL')}"
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
        payload = {
            "test": self._is_test,
            "language": "es",
            "command": "GET_BANKS_LIST",
            "merchant": {"apiLogin": self._api_login, "apiKey": self._api_key},
            "bankListInformation": {"paymentMethod": "PSE", "paymentCountry": "CO"},
        }
        response = await self._client.get_banks_list(self._environment, payload)
        banks = response.get("banks") or []
        return [
            GatewayFinancialInstitution(
                financial_institution_code=str(bank.get("pseCode", "")),
                financial_institution_name=bank.get("description", ""),
            )
            for bank in banks
        ]

    async def get_transaction(self, transaction_id: str) -> GatewayTransaction:
        """`transaction_id` aquí es en realidad NUESTRO `referenceCode` -- igual que
        `BoldGateway.get_transaction`, se reconsulta por el valor que nosotros elegimos
        (`ORDER_DETAIL_BY_REFERENCE_CODE`), no por un id interno de PayU."""
        payload = {
            "test": self._is_test,
            "language": "es",
            "command": "ORDER_DETAIL_BY_REFERENCE_CODE",
            "merchant": {"apiLogin": self._api_login, "apiKey": self._api_key},
            "details": {"referenceCode": transaction_id},
        }
        response = await self._client.order_detail_by_reference_code(
            self._environment, payload
        )
        orders = ((response.get("result") or {}).get("payload")) or []
        transactions = orders[0].get("transactions") if orders else None
        if not transactions:
            # PayU todavia no registro ningun intento contra esta referencia (el
            # deudor aun no volvio del banco) -- igual que `NO_TRANSACTION_FOUND` de
            # Bold, se trata como pendiente para que el polling siga reintentando.
            return GatewayTransaction(
                id=transaction_id,
                status=ReceivablesPaymentAttemptStatus.PENDING.value,
                amount_in_cents=0,
                currency="COP",
                reference=transaction_id,
                payment_method_type="PSE",
                raw=response,
            )
        last_transaction = transactions[-1]
        transaction_response = last_transaction.get("transactionResponse") or {}
        tx_value = (last_transaction.get("additionalValues") or {}).get(
            "TX_VALUE"
        ) or {}
        amount_in_cents = int(Decimal(str(tx_value.get("value", 0))) * 100)
        return GatewayTransaction(
            id=transaction_id,
            status=payu_transaction_state_to_attempt_status(
                transaction_response.get("state", "")
            ).value,
            amount_in_cents=amount_in_cents,
            currency=tx_value.get("currency", "COP"),
            reference=transaction_id,
            payment_method_type=str(last_transaction.get("paymentMethod", "PSE")),
            raw=response,
        )

    async def confirm_daviplata_otp(
        self, transaction_id: str, id_session_token: str, otp: str
    ) -> GatewayTransaction:
        """Solo ePayco tiene este concepto -- PayU no tiene Daviplata."""
        raise NotImplementedError("PayU no soporta Daviplata.")

    def verify_webhook_signature(self, event_body: dict[str, Any]) -> bool:
        """A diferencia de Bold (firma sobre bytes crudos), la confirmación de PayU
        llega como POST de formulario con los campos ya planos -- se puede verificar
        directamente sobre el `dict` ya parseado, como Wompi."""
        fields = {str(k): str(v) for k, v in event_body.items()}
        return verify_payu_confirmation_signature(fields, self._api_key)

    def supports_automatic_charge(self) -> bool:
        return False

    def supports_saved_payment_sources(self) -> bool:
        return False

    @staticmethod
    def _to_transaction(
        response: dict[str, Any],
        reference: str,
        amount_in_cents: int,
        currency: str,
        payment_method_type: str,
    ) -> GatewayTransaction:
        """`payment_method_type` es el método con el que SE MANDÓ la transacción
        (`PSE`/`NEQUI`/`BANCOLOMBIA_BUTTON`) -- NEQUI nunca trae `BANK_URL` (es
        asíncrona por notificación push, no por redirección)."""
        transaction_response = response.get("transactionResponse") or {}
        extra_parameters = transaction_response.get("extraParameters") or {}
        bank_url = extra_parameters.get("BANK_URL")
        redirect_action = (
            RedirectAction(redirect_url=bank_url, redirect_method="GET")
            if bank_url
            else None
        )
        # `id` se puebla con NUESTRO `reference`, no con el id interno de PayU -- mismo
        # criterio que `BoldGateway._to_transaction` (ver `get_transaction`).
        return GatewayTransaction(
            id=reference,
            status=payu_transaction_state_to_attempt_status(
                transaction_response.get("state", "")
            ).value,
            amount_in_cents=amount_in_cents,
            currency=currency,
            reference=reference,
            payment_method_type=payment_method_type,
            raw=response,
            redirect_action=redirect_action,
        )
