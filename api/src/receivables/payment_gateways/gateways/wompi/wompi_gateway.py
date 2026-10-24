"""Adaptador de Wompi: implementa el Protocol de pasarela de cobro de receivables."""

import html
from typing import Any

from receivables.payment_gateways.gateways.base import (
    AcceptanceTokens,
    BancolombiaTransferPaymentMethod,
    BrowserInfo,
    CardPaymentMethod,
    DeviceInfo,
    NequiPaymentMethod,
    PaymentMethodInput,
    PsePaymentMethod,
    ThreeDsChallenge,
    GatewayFinancialInstitution,
    GatewayPaymentSource,
    GatewayTransaction,
)
from receivables.payment_gateways.gateways.wompi.wompi_client import WompiClient
from receivables.payment_gateways.gateways.wompi.wompi_signature import (
    build_integrity_signature,
    verify_webhook_checksum,
)
from receivables.payment_gateways.services.payment_gateway_credential_service import (
    DecryptedGatewayCredential,
)


class WompiGateway:
    """Adaptador Wompi para `receivables` (deudor -> empresa). Cada instancia ya trae
    las credenciales de UNA organizacion resueltas (ver `resolver.py`) — a diferencia de
    `billing/gateways/bold`/`mercadopago`, no hay cuenta compartida por pais.

    Contrato de `credentials.values` esperado (ver
    `OrganizationGatewayCredentialModel`): `public_key`/`environment` en
    `public_config` (planos); `private_key`, `integrity_secret`, `events_secret`
    en `secrets` (cifrados, ya descifrados aqui)."""

    name = "WOMPI"

    def __init__(self, credentials: DecryptedGatewayCredential) -> None:
        self._credentials = credentials
        self._client = WompiClient()

    @property
    def _public_key(self) -> str:
        return self._credentials.get("public_key") or ""

    @property
    def _private_key(self) -> str:
        return self._credentials.get("private_key") or ""

    @property
    def _integrity_secret(self) -> str:
        return self._credentials.get("integrity_secret") or ""

    @property
    def _events_secret(self) -> str:
        return self._credentials.get("events_secret") or ""

    @property
    def _environment(self) -> str:
        return self._credentials.get("environment") or "sandbox"

    async def get_acceptance_tokens(self) -> AcceptanceTokens:
        info = await self._client.get_merchant_info(self._public_key, self._environment)
        data = info.get("data") or {}
        presigned_acceptance = data.get("presigned_acceptance") or {}
        presigned_personal = data.get("presigned_personal_data_auth") or {}
        return AcceptanceTokens(
            acceptance_token=presigned_acceptance.get("acceptance_token", ""),
            acceptance_permalink=presigned_acceptance.get("permalink", ""),
            personal_data_token=presigned_personal.get("acceptance_token", ""),
            personal_data_permalink=presigned_personal.get("permalink", ""),
        )

    async def create_transaction(
        self,
        reference: str,
        amount_in_cents: int,
        currency: str,
        payment_method: PaymentMethodInput | None,
        acceptance_token: str,
        accept_personal_auth: str,
        customer_email: str,
        payment_source_id: str | None = None,
        browser_info: BrowserInfo | None = None,
        device_info: DeviceInfo | None = None,  # pylint: disable=unused-argument
    ) -> GatewayTransaction:
        signature = build_integrity_signature(
            reference, amount_in_cents, currency, self._integrity_secret
        )
        payload: dict[str, Any] = {
            "acceptance_token": acceptance_token,
            "accept_personal_auth": accept_personal_auth,
            "amount_in_cents": amount_in_cents,
            "currency": currency,
            "customer_email": customer_email,
            "reference": reference,
            "signature": signature,
        }
        if isinstance(payment_method, CardPaymentMethod):
            # La tarjeta se tokeniza aquí mismo (server-to-server, con la public_key ya
            # descifrada) -- el frontend nunca ve ni necesita esa llave (skill
            # `wompi-gateway`, Paso 5).
            token = await self.tokenize_card(
                payment_method.number,
                payment_method.cvc,
                payment_method.exp_month,
                payment_method.exp_year,
                payment_method.card_holder,
            )
            payload["payment_method"] = {
                "type": "CARD",
                "installments": payment_method.installments,
                "token": token,
            }
        # Cobro contra una fuente de pago guardada (recurrente/3RI): se manda
        # `payment_source_id` en vez de `payment_method` (skill `wompi-gateway`,
        # Paso 5.3).
        elif payment_source_id is not None:
            payload["payment_source_id"] = payment_source_id
        elif payment_method is not None:
            payload["payment_method"] = self._build_payment_method_payload(
                payment_method
            )
        else:
            raise ValueError(
                "create_transaction requiere payment_method o payment_source_id."
            )

        if browser_info is not None:
            # 3D Secure v2 (challenge_v2) para CARD -- confirmado contra
            # docs.wompi.co/en/docs/colombia/transacciones-con-3d-secure-v2/ (skill
            # `wompi-gateway`, Paso 6). No aplica a PSE/NEQUI/BANCOLOMBIA_TRANSFER.
            payload["is_three_ds"] = True
            payload["three_ds_auth_type"] = "challenge_v2"
            payload["customer_data"] = {
                "browser_info": {
                    "browser_color_depth": browser_info.browser_color_depth,
                    "browser_screen_height": browser_info.browser_screen_height,
                    "browser_screen_width": browser_info.browser_screen_width,
                    "browser_language": browser_info.browser_language,
                    "browser_user_agent": browser_info.browser_user_agent,
                    "browser_tz": browser_info.browser_tz,
                }
            }

        response = await self._client.create_transaction(
            self._private_key, self._environment, payload
        )
        return self._to_transaction(response)

    @staticmethod
    def _build_payment_method_payload(
        payment_method: PaymentMethodInput,
    ) -> dict[str, Any]:
        """CARD no pasa por aquí -- `create_transaction` la tokeniza y construye su
        payload antes de llegar a este punto (necesita await, esto es sync)."""
        if isinstance(payment_method, PsePaymentMethod):
            return {
                "type": "PSE",
                "user_type": payment_method.user_type,
                "user_legal_id_type": payment_method.user_legal_id_type,
                "user_legal_id": payment_method.user_legal_id,
                "financial_institution_code": payment_method.financial_institution_code,
                "payment_description": payment_method.payment_description,
            }
        if isinstance(payment_method, NequiPaymentMethod):
            return {"type": "NEQUI", "phone_number": payment_method.phone_number}
        if isinstance(payment_method, BancolombiaTransferPaymentMethod):
            return {
                "type": "BANCOLOMBIA_TRANSFER",
                "payment_description": payment_method.payment_description,
            }
        raise ValueError(f"Metodo de pago no soportado: {type(payment_method)!r}")

    async def tokenize_card(
        self, number: str, cvc: str, exp_month: str, exp_year: str, card_holder: str
    ) -> str:
        response = await self._client.tokenize_card(
            self._public_key,
            self._environment,
            {
                "number": number,
                "cvc": cvc,
                "exp_month": exp_month,
                "exp_year": exp_year,
                "card_holder": card_holder,
            },
        )
        return str((response.get("data") or {}).get("id", ""))

    async def tokenize_nequi(self, phone_number: str) -> str:
        response = await self._client.tokenize_nequi(
            self._public_key, self._environment, phone_number
        )
        return str((response.get("data") or {}).get("id", ""))

    async def create_payment_source(
        self,
        type: str,
        token: str,
        customer_email: str,
        acceptance_token: str,
        accept_personal_auth: str,
    ) -> GatewayPaymentSource:
        payload = {
            "type": type,
            "token": token,
            "customer_email": customer_email,
            "acceptance_token": acceptance_token,
            "accept_personal_auth": accept_personal_auth,
        }
        response = await self._client.create_payment_source(
            self._private_key, self._environment, payload
        )
        data = response.get("data") or {}
        return GatewayPaymentSource(
            id=str(data.get("id", "")),
            status=data.get("status", ""),
            type=data.get("type", type),
            raw=data,
        )

    async def list_pse_financial_institutions(
        self,
    ) -> list[GatewayFinancialInstitution]:
        response = await self._client.list_pse_financial_institutions(
            self._private_key, self._environment
        )
        return [
            GatewayFinancialInstitution(
                financial_institution_code=str(
                    row.get("financial_institution_code", "")
                ),
                financial_institution_name=row.get("financial_institution_name", ""),
            )
            for row in (response.get("data") or [])
        ]

    async def confirm_daviplata_otp(
        self, transaction_id: str, id_session_token: str, otp: str
    ) -> GatewayTransaction:
        """Solo ePayco tiene este concepto -- Wompi no tiene Daviplata."""
        raise NotImplementedError("Wompi no soporta Daviplata.")

    async def get_transaction(self, transaction_id: str) -> GatewayTransaction:
        response = await self._client.get_transaction(
            self._private_key, self._environment, transaction_id
        )
        return self._to_transaction(response)

    @staticmethod
    def _to_transaction(response: dict[str, Any]) -> GatewayTransaction:
        data = response.get("data") or {}
        payment_method_data = data.get("payment_method") or {}
        return GatewayTransaction(
            id=str(data.get("id", "")),
            status=data.get("status", ""),
            amount_in_cents=int(data.get("amount_in_cents") or 0),
            currency=data.get("currency", ""),
            reference=data.get("reference", ""),
            payment_method_type=payment_method_data.get("type", ""),
            raw=data,
            three_ds_challenge=WompiGateway._extract_three_ds_challenge(
                payment_method_data
            ),
        )

    @staticmethod
    def _extract_three_ds_challenge(
        payment_method_data: dict[str, Any],
    ) -> ThreeDsChallenge | None:
        """Solo hay reto que mostrar cuando Wompi deja el paso actual en `PENDING`
        (skill `wompi-gateway`, Paso 6) -- el HTML del iframe llega escapado
        (`&lt;iframe...`) y hay que decodificarlo antes de pasarlo al frontend."""
        three_ds_auth = (payment_method_data.get("extra") or {}).get(
            "three_ds_auth"
        ) or {}
        challenge_html = three_ds_auth.get("three_ds_method_data")
        current_step_status = three_ds_auth.get("current_step_status")
        if not challenge_html or current_step_status != "PENDING":
            return None
        return ThreeDsChallenge(
            current_step=three_ds_auth.get("current_step", ""),
            current_step_status=current_step_status,
            challenge_html=html.unescape(challenge_html),
        )

    def verify_webhook_signature(self, event_body: dict[str, Any]) -> bool:
        return verify_webhook_checksum(event_body, self._events_secret)

    def supports_automatic_charge(self) -> bool:
        """Bandera propia de la organización (`public_config.wompi_3ri_enabled`),
        activada manualmente cuando esa organización consiguió la activación de fraude
        de Wompi para 3RI (skill `wompi-gateway`, Paso 6) — no hay forma de consultarlo
        vía API, Wompi lo activa por fuera."""
        return (
            str(self._credentials.get("wompi_3ri_enabled", "")).strip().lower()
            == "true"
        )

    def supports_saved_payment_sources(self) -> bool:
        return True
