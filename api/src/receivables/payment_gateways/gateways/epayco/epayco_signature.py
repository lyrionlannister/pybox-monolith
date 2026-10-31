"""Firma SHA-256 de ePayco para la URL de confirmación -- confirmada contra
docs.epayco.com/docs/checkout-respuesta-y-confirmacion (vigente, no la versión
`stale` de docs/url-de-confirmacion), que trae el mismo ejemplo en Node/PHP/Python."""

import hashlib
import hmac


def verify_epayco_confirmation_signature(
    fields: dict[str, str], customer_id: str, p_key: str
) -> bool:
    """SHA256(p_cust_id_cliente^p_key^x_ref_payco^x_transaction_id^x_amount^
    x_currency_code), comparado contra `x_signature`. `customer_id`/`p_key` son
    credenciales propias de ePayco para esto -- NO las mismas `public_key`/
    `private_key` que autentican contra la API REST (login). Un `p_key` vacío
    (credencial incompleta: `create`/`update` de
    `OrganizationGatewayCredentialManagementService` no exige campos por proveedor)
    se rechaza explícitamente -- de lo contrario la firma queda calculable por
    cualquiera que sepa que ese campo está vacío."""
    if not p_key:
        return False
    x_ref_payco = fields.get("x_ref_payco", "")
    x_transaction_id = fields.get("x_transaction_id", "")
    x_amount = fields.get("x_amount", "")
    x_currency_code = fields.get("x_currency_code", "")
    received_signature = fields.get("x_signature", "")
    message = (
        f"{customer_id}^{p_key}^{x_ref_payco}^{x_transaction_id}^"
        f"{x_amount}^{x_currency_code}"
    )
    expected_signature = hashlib.sha256(message.encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected_signature.lower(), received_signature.lower())
