"""Cliente HTTP a la Orders API de Mercado Pago."""

from typing import Any

from core.config.logger import logger
from core.payment_gateways.gateway_http_client import GatewayHttpClient
from core.tools.config_tools import get_or_throw


class MercadoPagoClient(GatewayHttpClient):
    """Cliente HTTP a la Orders API de Mercado Pago (Checkout API moderno)."""

    _API_BASE = "https://api.mercadopago.com"
    _LOG_TAG = "mercadopago"

    def _sandbox_safe_email(self, payer_email: str) -> str:
        """
        El token de MP en development es de sandbox: cualquier email que no
        termine en '@testuser.com' responde 400 'invalid_email_for_sandbox'. Se
        sustituye el dominio solo en development para poder probar el flujo
        completo.
        """
        if get_or_throw("ENV") != "development":
            return payer_email

        local_part = payer_email.split("@")[0]
        sandbox_email = f"{local_part}@testuser.com"
        logger.info(
            "[mercadopago] development: usando email de sandbox '%s' en vez de '%s'",
            sandbox_email,
            payer_email,
        )
        return sandbox_email

    async def create_order_manual(
        self,
        access_token: str,
        reference: str,
        amount: int,
        description: str,
        payer_email: str,
    ) -> dict[str, Any]:
        # URL de la doc no se puede partir sin romperla
        # pylint: disable=line-too-long
        """
        Crea una Order en modo manual: no cobra de inmediato, devuelve
        `client_token` para que el frontend capture la tarjeta via Secure
        Fields/SDK JS y procese la transaccion directamente contra Mercado Pago,
        sin pasar la tarjeta por este backend.

        `processing_mode: "manual"` y `payer.email` son obligatorios para la
        Orders API: sin `processing_mode` exige `transactions` de inmediato (modo
        automatico); sin `payer` responde 400 "minimum 1 properties allowed, but
        found 0 properties". `access_token` viene de las credenciales del pais
        resuelto para la organizacion (ver mercadopago_credentials.py), nunca de
        una cuenta fija.

        La Orders API no acepta un `currency_id` explicito (400
        "unsupported_properties"): la moneda la infiere del pais de la
        cuenta/aplicacion duena del access_token, por eso cada pais necesita su
        propia cuenta de MP en vez de compartir una sola.
        Docs:
        https://www.mercadopago.com.mx/developers/es/docs/checkout-api-orders/integration-model
        """
        # pylint: enable=line-too-long
        amount_str = f"{amount}.00"
        payer_email = self._sandbox_safe_email(payer_email)

        body = {
            "type": "online",
            "processing_mode": "manual",
            "external_reference": reference,
            "total_amount": amount_str,
            "payer": {"email": payer_email},
            "items": [{"title": description, "quantity": 1, "unit_price": amount_str}],
        }

        response = await self._http.post(
            f"{self._API_BASE}/v1/orders",
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Idempotency-Key": reference,
            },
        )
        self._log_error(response, "create_order_manual")
        response.raise_for_status()
        return response.json()

    async def get_order(self, access_token: str, order_id: str) -> dict[str, Any]:
        response = await self._http.get(
            f"{self._API_BASE}/v1/orders/{order_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()

    async def add_transaction(
        self,
        access_token: str,
        order_id: str,
        amount: int,
        token: str,
        payment_method_id: str,
        payment_type: str,
        installments: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        Agrega la transaccion de tarjeta a una Order en modo manual (la tarjeta ya
        fue tokenizada en el frontend via Secure Fields, el token nunca pasa por
        este backend en texto plano). No ejecuta el cobro todavia, eso lo hace
        `process_order`.

        `payment_method_id` y `payment_type` vienen de
        `mp.getPaymentMethods({bin})` en el frontend: para credito el id es
        'visa'/'master'/'amex' con type 'credit_card'; para debito es
        'debvisa'/'debmaster'/... con type 'debit_card'. MP rechaza (400) si el id
        no corresponde al type, por eso NO se hardcodea el tipo.

        `X-Idempotency-Key` es obligatorio: sin el header, MP responde 400
        "Missing HTTP header: X-Idempotency-Key". Se usa el id del intento de pago
        para que un reintento del mismo intento no duplique la transaccion.
        """
        payment_method: dict[str, Any] = {
            "id": payment_method_id,
            "type": payment_type,
            "token": token,
        }
        # Solo el credito admite cuotas. En debito, MP rechaza (400
        # "additionalProperties 'installments' not allowed") si se manda el
        # campo, asi que se omite.
        if payment_type == "credit_card":
            payment_method["installments"] = installments

        body = {
            "payments": [{"amount": f"{amount}.00", "payment_method": payment_method}]
        }
        response = await self._http.post(
            f"{self._API_BASE}/v1/orders/{order_id}/transactions",
            json=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Idempotency-Key": idempotency_key,
            },
        )
        self._log_error(response, f"add_transaction order_id={order_id}")
        response.raise_for_status()
        return response.json()

    async def process_order(
        self, access_token: str, order_id: str, idempotency_key: str
    ) -> dict[str, Any]:
        """
        Ejecuta (cobra) las transacciones ya agregadas a una Order en modo manual.

        MP responde con error HTTP (400 por schema, 402 cuando el pago es
        rechazado por el banco/usuario, etc.) pero para un rechazo legitimo el
        body trae `data` con la orden completa (status "failed"). En ese caso se
        devuelve la orden igual para que el llamador la mapee a un intento
        rechazado en vez de explotar como error interno.
        """
        response = await self._http.post(
            f"{self._API_BASE}/v1/orders/{order_id}/process",
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Idempotency-Key": idempotency_key,
            },
        )
        if response.is_error:
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and isinstance(body.get("data"), dict):
                # Rechazo legitimo (ej. 402 invalid_users_involved /
                # rejected_by_issuer): la orden viene en `data` con status
                # "failed"; se retorna para mapearla.
                logger.warning(
                    "[mercadopago] process_order order_id=%s rechazado | "
                    "status=%s status_detail=%s",
                    order_id,
                    response.status_code,
                    body["data"].get("status_detail"),
                )
                return body["data"]
        self._log_error(response, f"process_order order_id={order_id}")
        response.raise_for_status()
        return response.json()
