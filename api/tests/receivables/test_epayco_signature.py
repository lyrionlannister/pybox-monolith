"""Firma de ePayco -- `test_matches_official_example` usa el ejemplo textual publicado
en docs.epayco.com/docs/checkout-respuesta-y-confirmacion (sección "Validación de
Firma de Seguridad"), que trae el mismo caso en Node/PHP/Python."""

import hashlib

from receivables.payment_gateways.gateways.epayco.epayco_signature import (
    verify_epayco_confirmation_signature,
)


class TestVerifyEpaycoConfirmationSignature:
    def _fields(self, **overrides: str) -> dict[str, str]:
        base = {
            "x_ref_payco": "26291500",
            "x_transaction_id": "705885651",
            "x_amount": "10000",
            "x_currency_code": "COP",
        }
        base.update(overrides)
        return base

    def test_matches_official_example(self):
        fields = self._fields()
        message = "28770^p-key-test^26291500^705885651^10000^COP"
        fields["x_signature"] = hashlib.sha256(message.encode("utf-8")).hexdigest()
        assert verify_epayco_confirmation_signature(fields, "28770", "p-key-test")

    def test_rejects_mismatched_signature(self):
        fields = self._fields(x_signature="deadbeef")
        assert not verify_epayco_confirmation_signature(fields, "28770", "p-key-test")

    def test_rejects_when_customer_id_or_p_key_differ(self):
        fields = self._fields()
        message = "28770^p-key-test^26291500^705885651^10000^COP"
        fields["x_signature"] = hashlib.sha256(message.encode("utf-8")).hexdigest()
        assert not verify_epayco_confirmation_signature(fields, "28770", "wrong-p-key")

    def test_rejects_empty_p_key_even_if_signature_matches(self):
        """Credencial incompleta (p_key vacío) no debe aceptar una firma calculada
        con esa misma llave vacía -- sería trivialmente falsificable."""
        fields = self._fields()
        message = "28770^^26291500^705885651^10000^COP"
        fields["x_signature"] = hashlib.sha256(message.encode("utf-8")).hexdigest()
        assert not verify_epayco_confirmation_signature(fields, "28770", "")
