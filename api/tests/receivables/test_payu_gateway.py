"""PayUGateway: construcción del payload de `SUBMIT_TRANSACTION` para PSE/NEQUI/
BANCOLOMBIA_BUTTON, mapeo de la respuesta (redirección vía `BANK_URL`), reconsulta por
referencia (`ORDER_DETAIL_BY_REFERENCE_CODE`) y verificación de la firma de
confirmación -- el cliente HTTP real (`PayUClient`) se mockea, nunca pega a PayU.
Tarjeta no está implementada (ver docstring de `PayUGateway`): solo se cubre que
levante `NotImplementedError`."""

import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from receivables.payment_gateways.enums.payment_gateway_enums import (
    ReceivablesGatewayProvider,
    ReceivablesPaymentAttemptStatus,
)
from receivables.payment_gateways.gateways.base import (
    BancolombiaTransferPaymentMethod,
    CardPaymentMethod,
    DeviceInfo,
    NequiPaymentMethod,
    PsePaymentMethod,
)
from receivables.payment_gateways.gateways.payu import (
    payu_gateway as payu_gateway_module,
)
from receivables.payment_gateways.gateways.payu.payu_gateway import PayUGateway
from receivables.payment_gateways.services.payment_gateway_credential_service import (
    DecryptedGatewayCredential,
)

_RETURN_URL = "https://app.test/credits/payments/payment-return"
_NOTIFY_URL_BASE = "https://api.test/api/v1/webhooks/payu"


def _device_info(**overrides) -> DeviceInfo:
    base = {
        "device_session_id": "device-session-1",
        "cookie": "device-session-1",
        "user_agent": "pytest",
        "ip_address": "127.0.0.1",
    }
    base.update(overrides)
    return DeviceInfo(**base)


def _credentials(**values: str) -> DecryptedGatewayCredential:
    base = {
        "api_key": "test-api-key",
        "api_login": "test-api-login",
        "merchant_id": "508029",
        "account_id": "512321",
        "environment": "sandbox",
    }
    base.update(values)
    return DecryptedGatewayCredential(
        organization_id=uuid.uuid4(),
        provider=ReceivablesGatewayProvider.PAYU,
        values=base,
        lookup_key=None,
    )


def _pse_payment_method(**overrides) -> PsePaymentMethod:
    base = {
        "user_type": 0,
        "user_legal_id_type": "CC",
        "user_legal_id": "123456789",
        "financial_institution_code": "1051",
        "payment_description": "Pago cuota",
        "full_name": "Juan Perez",
        "phone": "3001234567",
        "address": "Calle 1 # 2-3",
        "city": "Bogota",
    }
    base.update(overrides)
    return PsePaymentMethod(**base)


def _nequi_payment_method(**overrides) -> NequiPaymentMethod:
    base = {
        "phone_number": "3001234567",
        "full_name": "Juan Perez",
        "user_legal_id": "123456789",
        "user_legal_id_type": "CC",
        "address": "Calle 1 # 2-3",
        "city": "Bogota",
        "payment_description": "Pago cuota",
    }
    base.update(overrides)
    return NequiPaymentMethod(**base)


def _bancolombia_payment_method(**overrides) -> BancolombiaTransferPaymentMethod:
    base = {
        "payment_description": "Pago cuota",
        "full_name": "Juan Perez",
        "phone": "3001234567",
        "user_legal_id": "123456789",
        "user_legal_id_type": "CC",
        "address": "Calle 1 # 2-3",
        "city": "Bogota",
    }
    base.update(overrides)
    return BancolombiaTransferPaymentMethod(**base)


def _make_gateway(monkeypatch, **credential_overrides) -> PayUGateway:
    monkeypatch.setattr(
        payu_gateway_module,
        "get_or_throw",
        MagicMock(
            side_effect=lambda key: {
                "RECEIVABLES_PAYMENT_REDIRECT_RETURN_URL": _RETURN_URL,
                "RECEIVABLES_PAYU_NOTIFY_URL": _NOTIFY_URL_BASE,
            }[key]
        ),
    )
    gateway = PayUGateway(_credentials(**credential_overrides))
    gateway._client = AsyncMock()  # pylint: disable=protected-access
    return gateway


class TestCreateTransaction:
    async def test_card_payment_method_is_not_supported(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        card = CardPaymentMethod(
            number="4242424242424242",
            cvc="123",
            exp_month="12",
            exp_year="29",
            card_holder="Test",
        )
        with pytest.raises(NotImplementedError):
            await gateway.create_transaction(
                reference="PAG-1",
                amount_in_cents=6_500_000,
                currency="COP",
                payment_method=card,
                acceptance_token="",
                accept_personal_auth="",
                customer_email="debtor@example.com",
                device_info=_device_info(),
            )

    async def test_missing_device_info_raises_value_error(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        pse = _pse_payment_method()
        with pytest.raises(ValueError):
            await gateway.create_transaction(
                reference="PAG-1",
                amount_in_cents=6_500_000,
                currency="COP",
                payment_method=pse,
                acceptance_token="",
                accept_personal_auth="",
                customer_email="debtor@example.com",
            )

    async def test_missing_payer_data_raises_value_error(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        pse = _pse_payment_method(full_name="")
        with pytest.raises(ValueError):
            await gateway.create_transaction(
                reference="PAG-1",
                amount_in_cents=6_500_000,
                currency="COP",
                payment_method=pse,
                acceptance_token="",
                accept_personal_auth="",
                customer_email="debtor@example.com",
                device_info=_device_info(),
            )

    async def test_pse_payment_returns_redirect_action(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.submit_transaction.return_value = {
            "code": "SUCCESS",
            "transactionResponse": {
                "state": "PENDING",
                "extraParameters": {"BANK_URL": "https://bank.test/confirm"},
            },
        }
        pse = _pse_payment_method()

        transaction = await gateway.create_transaction(
            reference="PAG-1",
            amount_in_cents=6_500_000,
            currency="COP",
            payment_method=pse,
            acceptance_token="",
            accept_personal_auth="",
            customer_email="debtor@example.com",
            device_info=_device_info(),
        )

        assert transaction.status == ReceivablesPaymentAttemptStatus.PENDING.value
        assert transaction.payment_method_type == "PSE"
        assert transaction.redirect_action is not None
        assert transaction.redirect_action.redirect_url == "https://bank.test/confirm"

        # pylint: disable=protected-access
        payload = gateway._client.submit_transaction.await_args.args[1]
        organization_id = gateway._credentials.organization_id
        # pylint: enable=protected-access
        order = payload["transaction"]["order"]
        assert order["accountId"] == "512321"
        assert order["notifyUrl"] == f"{_NOTIFY_URL_BASE}/{organization_id}"
        extra_parameters = payload["transaction"]["extraParameters"]
        assert extra_parameters["RESPONSE_URL"] == f"{_RETURN_URL}?reference=PAG-1"
        assert extra_parameters["FINANCIAL_INSTITUTION_CODE"] == "1051"
        assert payload["transaction"]["payer"]["dniNumber"] == "123456789"
        assert payload["transaction"]["deviceSessionId"] == "device-session-1"
        assert payload["transaction"]["ipAddress"] == "127.0.0.1"
        assert payload["transaction"]["cookie"] == "device-session-1"
        assert payload["transaction"]["userAgent"] == "pytest"

    async def test_pse_payment_rounds_amount_to_whole_peso(self, monkeypatch):
        """PayU factura en pesos enteros: 6_500_075 centavos (65000.75 COP) debe
        redondearse HALF_UP a 65001 COP, y el `amount_in_cents` de la transacción
        devuelta debe reflejar ese redondeo (65_001_00), no el crudo sin redondear --
        si no, `attempt_status_sync` compara mal contra lo que PayU reporta después."""
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.submit_transaction.return_value = {
            "code": "SUCCESS",
            "transactionResponse": {
                "state": "PENDING",
                "extraParameters": {"BANK_URL": "https://bank.test/confirm"},
            },
        }
        pse = _pse_payment_method()

        transaction = await gateway.create_transaction(
            reference="PAG-1",
            amount_in_cents=6_500_075,
            currency="COP",
            payment_method=pse,
            acceptance_token="",
            accept_personal_auth="",
            customer_email="debtor@example.com",
            device_info=_device_info(),
        )

        assert transaction.amount_in_cents == 6_500_100

        # pylint: disable=protected-access
        payload = gateway._client.submit_transaction.await_args.args[1]
        # pylint: enable=protected-access
        tx_value = payload["transaction"]["order"]["additionalValues"]["TX_VALUE"]
        assert tx_value["value"] == 65_001

    async def test_nequi_payment_is_pending_without_redirect(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.submit_transaction.return_value = {
            "code": "SUCCESS",
            "transactionResponse": {"state": "PENDING", "extraParameters": None},
        }
        nequi = _nequi_payment_method()

        transaction = await gateway.create_transaction(
            reference="PAG-2",
            amount_in_cents=6_500_000,
            currency="COP",
            payment_method=nequi,
            acceptance_token="",
            accept_personal_auth="",
            customer_email="debtor@example.com",
            device_info=_device_info(),
        )

        assert transaction.status == ReceivablesPaymentAttemptStatus.PENDING.value
        assert transaction.payment_method_type == "NEQUI"
        assert transaction.redirect_action is None

        # pylint: disable=protected-access
        payload = gateway._client.submit_transaction.await_args.args[1]
        # pylint: enable=protected-access
        assert payload["transaction"]["paymentMethod"] == "NEQUI"
        assert payload["transaction"]["payer"]["contactPhone"] == "3001234567"
        assert payload["transaction"]["payer"]["dniNumber"] == "123456789"
        assert payload["transaction"]["order"]["buyer"]["dniNumber"] == "123456789"

    async def test_nequi_missing_document_raises_value_error(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        nequi = _nequi_payment_method(user_legal_id=None)
        with pytest.raises(ValueError):
            await gateway.create_transaction(
                reference="PAG-2",
                amount_in_cents=6_500_000,
                currency="COP",
                payment_method=nequi,
                acceptance_token="",
                accept_personal_auth="",
                customer_email="debtor@example.com",
                device_info=_device_info(),
            )

    async def test_bancolombia_payment_returns_redirect_action(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.submit_transaction.return_value = {
            "code": "SUCCESS",
            "transactionResponse": {
                "state": "PENDING",
                "extraParameters": {"BANK_URL": "https://bancolombia.test/confirm"},
            },
        }
        bancolombia = _bancolombia_payment_method()

        transaction = await gateway.create_transaction(
            reference="PAG-3",
            amount_in_cents=6_500_000,
            currency="COP",
            payment_method=bancolombia,
            acceptance_token="",
            accept_personal_auth="",
            customer_email="debtor@example.com",
            device_info=_device_info(),
        )

        assert transaction.status == ReceivablesPaymentAttemptStatus.PENDING.value
        assert transaction.payment_method_type == "BANCOLOMBIA_BUTTON"
        assert transaction.redirect_action is not None
        assert (
            transaction.redirect_action.redirect_url
            == "https://bancolombia.test/confirm"
        )

        # pylint: disable=protected-access
        payload = gateway._client.submit_transaction.await_args.args[1]
        # pylint: enable=protected-access
        assert payload["transaction"]["paymentMethod"] == "BANCOLOMBIA_BUTTON"
        assert payload["transaction"]["payer"]["contactPhone"] == "3001234567"


class TestGetTransaction:
    async def test_no_transaction_found_is_pending(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.order_detail_by_reference_code.return_value = {
            "code": "SUCCESS",
            "result": {"payload": []},
        }

        transaction = await gateway.get_transaction("PAG-1")
        assert transaction.status == ReceivablesPaymentAttemptStatus.PENDING.value

    async def test_approved_transaction_is_mapped(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.order_detail_by_reference_code.return_value = {
            "code": "SUCCESS",
            "result": {
                "payload": [
                    {
                        "transactions": [
                            {
                                "paymentMethod": "PSE",
                                "transactionResponse": {"state": "APPROVED"},
                                "additionalValues": {
                                    "TX_VALUE": {"value": 65000.0, "currency": "COP"}
                                },
                            }
                        ]
                    }
                ]
            },
        }

        transaction = await gateway.get_transaction("PAG-1")
        assert transaction.status == ReceivablesPaymentAttemptStatus.APPROVED.value
        assert transaction.amount_in_cents == 6_500_000


class TestVerifyWebhookSignature:
    def test_delegates_to_payu_signature_module(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        message = "test-api-key~508029~PAG-1~65000.0~COP~4"
        body = {
            "merchant_id": "508029",
            "reference_sale": "PAG-1",
            "value": "65000.00",
            "currency": "COP",
            "state_pol": "4",
            "sign": hashlib.md5(message.encode("utf-8")).hexdigest(),
        }
        assert gateway.verify_webhook_signature(body) is True
