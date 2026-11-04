"""Firma MD5 de PayU Latam para `receivables` -- dos fórmulas distintas, confirmadas
contra el SDK oficial (`SignatureUtil.php` de `payu-latam-php-payments-sdk`) y la
sección "Authentication Signature" de developers.payulatam.com, no contra terceros."""

import hashlib
import hmac
from decimal import Decimal, InvalidOperation


def build_payu_request_signature(
    api_key: str,
    merchant_id: str,
    reference_code: str,
    amount_in_cents: int,
    currency: str,
) -> str:
    """Firma de `SUBMIT_TRANSACTION`: MD5(apiKey~merchantId~referenceCode~valor~moneda).
    El `valor` va SIN decimales (COP es la única moneda de este módulo, y el propio
    SDK oficial de PayU formatea el valor de la firma sin parte decimal para COP) --
    distinto del formato de la firma de confirmación
    (`verify_payu_confirmation_signature`), que sí usa decimales."""
    value = str(amount_in_cents // 100)
    message = f"{api_key}~{merchant_id}~{reference_code}~{value}~{currency}"
    # MD5 lo fija el protocolo de firma de PayU, no es una elección nuestra.
    return hashlib.md5(message.encode("utf-8")).hexdigest()  # nosec B324


def verify_payu_confirmation_signature(fields: dict[str, str], api_key: str) -> bool:
    """Firma de la URL de confirmación (`notifyUrl`): MD5(apiKey~merchant_id~
    reference_sale~valor~moneda~state_pol). El `valor` (`TX_VALUE`/`value`) se formatea
    con un decimal si el segundo decimal es 0 (150.00 -> "150.0"), o con dos si no
    (150.25 se mantiene) -- regla documentada en la página de Confirmation URL de
    PayU, distinta de la firma de `SUBMIT_TRANSACTION`."""
    merchant_id = fields.get("merchant_id", "")
    reference_sale = fields.get("reference_sale", "")
    currency = fields.get("currency", "")
    state_pol = fields.get("state_pol", "")
    received_signature = fields.get("sign", "")
    try:
        raw_value = Decimal(fields.get("value", "0"))
    except InvalidOperation:
        return False
    value = _format_confirmation_value(raw_value)
    message = f"{api_key}~{merchant_id}~{reference_sale}~{value}~{currency}~{state_pol}"
    # MD5 lo fija el protocolo de firma de PayU, no es una elección nuestra.
    expected_signature = hashlib.md5(message.encode("utf-8")).hexdigest()  # nosec B324
    return hmac.compare_digest(expected_signature.lower(), received_signature.lower())


def _format_confirmation_value(value: Decimal) -> str:
    formatted = f"{value:.2f}"
    return formatted[:-1] if formatted.endswith("0") else formatted
