"""`_to_gateway_payment_method`: los datos del pagador que exigen PayU/ePayco deben
llegar del request al método de pago (PSE y Transferencia Bancolombia)."""

from receivables.payment_gateways.controllers.payment_checkout_controller import (
    _to_gateway_payment_method,
)
from receivables.payment_gateways.gateways.base import (
    BancolombiaTransferPaymentMethod,
    PsePaymentMethod,
)
from receivables.payment_gateways.schemas.payment_checkout_schemas import (
    BancolombiaTransferTransactionRequest,
    PseTransactionRequest,
)

_PAYER = {
    "fullName": "Ana Pérez",
    "phone": "3001234567",
    "address": "Calle 1 # 2-3",
    "city": "Bogotá",
}


def test_pse_maps_payer_fields():
    body = PseTransactionRequest.model_validate(
        {
            "userType": 0,
            "userLegalIdType": "CC",
            "userLegalId": "123456789",
            "financialInstitutionCode": "1007",
            "paymentDescription": "Pago cuota #3",
            "customerEmail": "debtor@example.com",
            **_PAYER,
        }
    )

    method = _to_gateway_payment_method(body)

    assert isinstance(method, PsePaymentMethod)
    assert (method.full_name, method.phone, method.address, method.city) == (
        "Ana Pérez",
        "3001234567",
        "Calle 1 # 2-3",
        "Bogotá",
    )


def test_bancolombia_maps_payer_fields_including_phone():
    body = BancolombiaTransferTransactionRequest.model_validate(
        {
            "paymentDescription": "Pago cuota #3",
            "customerEmail": "debtor@example.com",
            "userLegalIdType": "CC",
            "userLegalId": "123456789",
            **_PAYER,
        }
    )

    method = _to_gateway_payment_method(body)

    assert isinstance(method, BancolombiaTransferPaymentMethod)
    assert method.phone == "3001234567"
    assert method.full_name == "Ana Pérez"
