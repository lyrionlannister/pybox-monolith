"""BoldGateway: redondeo a peso entero del monto enviado a Bold -- el cliente HTTP
real (`BoldClient`) se mockea, nunca pega a Bold."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from receivables.payment_gateways.enums.payment_gateway_enums import (
    ReceivablesGatewayProvider,
)
from receivables.payment_gateways.gateways.base import NequiPaymentMethod
from receivables.payment_gateways.gateways.bold import (
    bold_gateway as bold_gateway_module,
)
from receivables.payment_gateways.gateways.bold.bold_gateway import BoldGateway
from receivables.payment_gateways.services.payment_gateway_credential_service import (
    DecryptedGatewayCredential,
)

_RETURN_URL = "https://app.test/credits/payments/payment-return"


def _credentials(**values: str) -> DecryptedGatewayCredential:
    base = {"identity_key": "test-identity-key", "secret_key": "test-secret-key"}
    base.update(values)
    return DecryptedGatewayCredential(
        organization_id=uuid.uuid4(),
        provider=ReceivablesGatewayProvider.BOLD,
        values=base,
        lookup_key=None,
    )


def _make_gateway(monkeypatch) -> BoldGateway:
    monkeypatch.setattr(
        bold_gateway_module,
        "get_or_throw",
        MagicMock(return_value=_RETURN_URL),
    )
    gateway = BoldGateway(_credentials())
    gateway._client = AsyncMock()  # pylint: disable=protected-access
    return gateway


class TestCreateTransactionRounding:
    pytestmark = pytest.mark.asyncio

    async def test_nequi_payment_rounds_amount_to_whole_peso(self, monkeypatch):
        """Bold factura en pesos enteros: 6_500_075 centavos (65000.75 COP) debe
        redondearse HALF_UP a 65001 COP, y el `amount_in_cents` de la transacción
        devuelta debe reflejar ese redondeo (65_001_00), no el crudo sin redondear --
        si no, `attempt_status_sync` compara mal contra lo que Bold reporta después."""
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.create_payment.return_value = {
            "status": "PENDING",
            "next_actions": {},
        }
        nequi = NequiPaymentMethod(phone_number="3001234567")

        transaction = await gateway.create_transaction(
            reference="PAG-1",
            amount_in_cents=6_500_075,
            currency="COP",
            payment_method=nequi,
            acceptance_token="",
            accept_personal_auth="",
            customer_email="debtor@example.com",
        )

        assert transaction.amount_in_cents == 6_500_100

        # pylint: disable=protected-access
        intent_payload = gateway._client.create_payment_intent.await_args.args[1]
        # pylint: enable=protected-access
        assert intent_payload["amount"]["total_amount"] == 65_001
