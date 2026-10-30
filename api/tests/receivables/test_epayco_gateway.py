"""EpaycoGateway: construcción del payload de PSE/Daviplata, mapeo de la respuesta
(redirección vía `urlbanco` para PSE, `OtpChallenge` para Daviplata), confirmación del
OTP de Daviplata, reconsulta por `ref_payco` (`/transaction/detail`) y verificación de
la firma de confirmación -- el cliente HTTP real (`EpaycoClient`) se mockea, nunca pega
a ePayco. Tarjeta no está implementada (ver docstring de `EpaycoGateway`): solo se
cubre que levante `NotImplementedError`."""

import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from receivables.payment_gateways.enums.payment_gateway_enums import (
    ReceivablesGatewayProvider,
    ReceivablesPaymentAttemptStatus,
)
from receivables.payment_gateways.gateways.base import (
    CardPaymentMethod,
    DaviplataPaymentMethod,
    DeviceInfo,
    PsePaymentMethod,
)
from receivables.payment_gateways.gateways.epayco import (
    epayco_gateway as epayco_gateway_module,
)
from receivables.payment_gateways.gateways.epayco.epayco_gateway import EpaycoGateway
from receivables.payment_gateways.services.payment_gateway_credential_service import (
    DecryptedGatewayCredential,
)

_RETURN_URL = "https://app.test/credits/payments/payment-return"
_NOTIFY_URL_BASE = "https://api.test/api/v1/webhooks/epayco"


def _device_info(**overrides) -> DeviceInfo:
    base = {
        "device_session_id": "",
        "cookie": "",
        "user_agent": "",
        "ip_address": "190.0.0.1",
    }
    base.update(overrides)
    return DeviceInfo(**base)


def _credentials(**values: str) -> DecryptedGatewayCredential:
    base = {
        "public_key": "test-public-key",
        "private_key": "test-private-key",
        "p_cust_id_cliente": "28770",
        "p_key": "test-p-key",
        "environment": "sandbox",
    }
    base.update(values)
    return DecryptedGatewayCredential(
        organization_id=uuid.uuid4(),
        provider=ReceivablesGatewayProvider.EPAYCO,
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


def _daviplata_payment_method(**overrides) -> DaviplataPaymentMethod:
    base = {
        "user_legal_id_type": "CC",
        "user_legal_id": "123456789",
        "full_name": "Juan Perez",
        "address": "Calle 1 # 2-3",
        "city": "Bogota",
        "phone": "3001234567",
    }
    base.update(overrides)
    return DaviplataPaymentMethod(**base)


def _make_gateway(monkeypatch, **credential_overrides) -> EpaycoGateway:
    monkeypatch.setattr(
        epayco_gateway_module,
        "get_or_throw",
        MagicMock(
            side_effect=lambda key: {
                "RECEIVABLES_PAYMENT_REDIRECT_RETURN_URL": _RETURN_URL,
                "RECEIVABLES_EPAYCO_NOTIFY_URL": _NOTIFY_URL_BASE,
            }[key]
        ),
    )
    gateway = EpaycoGateway(_credentials(**credential_overrides))
    gateway._client = AsyncMock()  # pylint: disable=protected-access
    # pylint: disable-next=protected-access
    gateway._client.login.return_value = {"token": "test-jwt"}
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

    async def test_pse_missing_payer_data_raises_value_error(self, monkeypatch):
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
        gateway._client.create_pse_transaction.return_value = {
            "success": True,
            "data": {
                "ref_payco": 26292245,
                "estado": "Pendiente",
                "urlbanco": "https://registro.pse.com.co/confirm",
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
            device_info=_device_info(ip_address="190.0.0.1"),
        )

        assert transaction.status == ReceivablesPaymentAttemptStatus.PENDING.value
        assert transaction.id == "26292245"
        assert transaction.redirect_action is not None
        assert transaction.redirect_action.redirect_url == (
            "https://registro.pse.com.co/confirm"
        )

        # pylint: disable=protected-access
        payload = gateway._client.create_pse_transaction.await_args.args[1]
        # pylint: enable=protected-access
        assert payload["bank"] == "1051"
        assert payload["docNumber"] == "123456789"
        assert payload["name"] == "Juan"
        assert payload["lastName"] == "Perez"
        assert payload["cellPhone"] == "3001234567"
        assert payload["phone"] == "3001234567"
        assert payload["ip"] == "190.0.0.1"
        assert payload["urlResponse"] == _RETURN_URL
        assert payload["urlConfirmation"] == (
            f"{_NOTIFY_URL_BASE}/{gateway._credentials.organization_id}"  # pylint: disable=protected-access
        )
        assert payload["testMode"] is True

    async def test_pse_payment_rounds_amount_to_whole_peso(self, monkeypatch):
        """ePayco factura en pesos enteros: 6_500_075 centavos (65000.75 COP) debe
        redondearse HALF_UP a 65001 COP, y el `amount_in_cents` de la transacción
        devuelta debe reflejar ese redondeo (65_001_00), no el crudo sin redondear."""
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.create_pse_transaction.return_value = {
            "success": True,
            "data": {
                "ref_payco": 26292245,
                "estado": "Pendiente",
                "urlbanco": "https://registro.pse.com.co/confirm",
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
            device_info=_device_info(ip_address="190.0.0.1"),
        )

        assert transaction.amount_in_cents == 6_500_100

        # pylint: disable=protected-access
        payload = gateway._client.create_pse_transaction.await_args.args[1]
        # pylint: enable=protected-access
        assert payload["value"] == "65001"

    async def test_daviplata_missing_payer_data_raises_value_error(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        daviplata = _daviplata_payment_method(full_name="")
        with pytest.raises(ValueError):
            await gateway.create_transaction(
                reference="PAG-2",
                amount_in_cents=100_00,
                currency="COP",
                payment_method=daviplata,
                acceptance_token="",
                accept_personal_auth="",
                customer_email="debtor@example.com",
                device_info=_device_info(),
            )

    async def test_daviplata_payment_returns_otp_challenge(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.create_daviplata_transaction.return_value = {
            "success": True,
            "data": {
                "transaction": {
                    "refPayco": 30612544,
                    "estatus": "Pendiente",
                    "idSessionToken": "session-token-123",
                }
            },
        }
        daviplata = _daviplata_payment_method()

        transaction = await gateway.create_transaction(
            reference="PAG-2",
            amount_in_cents=10_000_00,
            currency="COP",
            payment_method=daviplata,
            acceptance_token="",
            accept_personal_auth="",
            customer_email="debtor@example.com",
            device_info=_device_info(),
        )

        assert transaction.status == ReceivablesPaymentAttemptStatus.PENDING.value
        assert transaction.id == "30612544"
        assert transaction.otp_challenge is not None
        assert transaction.otp_challenge.transaction_id == "30612544"
        assert transaction.otp_challenge.id_session_token == "session-token-123"


class TestConfirmDaviplataOtp:
    async def test_confirms_and_maps_approved_status(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.confirm_daviplata_transaction.return_value = {
            "success": True,
            "data": {"refPayco": "30612544", "status": "Aceptada", "value": 100},
        }

        transaction = await gateway.confirm_daviplata_otp(
            "30612544", "session-token-123", "1234"
        )

        assert transaction.status == ReceivablesPaymentAttemptStatus.APPROVED.value
        assert transaction.amount_in_cents == 10_000

        # pylint: disable=protected-access
        payload = gateway._client.confirm_daviplata_transaction.await_args.args[1]
        # pylint: enable=protected-access
        assert payload == {
            "refPayco": "30612544",
            "idSessionToken": "session-token-123",
            "otp": "1234",
        }


class TestGetTransaction:
    async def test_no_transaction_found_is_pending(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.get_transaction_detail.return_value = {
            "success": False,
            "data": {"totalerrores": 1, "errores": []},
        }

        transaction = await gateway.get_transaction("26292245")
        assert transaction.status == ReceivablesPaymentAttemptStatus.PENDING.value

    async def test_approved_transaction_is_mapped(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.get_transaction_detail.return_value = {
            "success": True,
            "data": {
                "status": "Aceptada",
                "amount": 65000,
                "currency": "COP",
                "paymentMethod": "PSE",
            },
        }

        transaction = await gateway.get_transaction("26292245")
        assert transaction.status == ReceivablesPaymentAttemptStatus.APPROVED.value
        assert transaction.amount_in_cents == 6_500_000


class TestListPseFinancialInstitutions:
    async def test_filters_out_placeholder_bank(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        # pylint: disable-next=protected-access
        gateway._client.get_pse_banks.return_value = {
            "success": True,
            "data": [
                {"bankCode": "0", "bankName": "A continuación seleccione su banco"},
                {"bankCode": "1007", "bankName": "BANCOLOMBIA"},
            ],
        }

        institutions = await gateway.list_pse_financial_institutions()
        assert len(institutions) == 1
        assert institutions[0].financial_institution_code == "1007"
        assert institutions[0].financial_institution_name == "BANCOLOMBIA"


class TestVerifyWebhookSignature:
    def test_delegates_to_epayco_signature_module(self, monkeypatch):
        gateway = _make_gateway(monkeypatch)
        message = "28770^test-p-key^26291500^705885651^10000^COP"
        body = {
            "x_ref_payco": "26291500",
            "x_transaction_id": "705885651",
            "x_amount": "10000",
            "x_currency_code": "COP",
            "x_signature": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        }
        assert gateway.verify_webhook_signature(body) is True
