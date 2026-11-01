"""Firma HMAC del webhook de Bold -- developers.bold.co/webhook."""

import base64
import hashlib
import hmac

from receivables.payment_gateways.gateways.bold.bold_signature import (
    verify_bold_webhook_signature,
)


class TestVerifyBoldWebhookSignature:
    def _signature(self, raw_body: bytes, secret_key: str) -> str:
        encoded = base64.b64encode(raw_body)
        return hmac.new(secret_key.encode("utf-8"), encoded, hashlib.sha256).hexdigest()

    def test_matches_valid_signature(self):
        raw_body = b'{"event":"SALE_APPROVED"}'
        signature = self._signature(raw_body, "secret-test")
        assert verify_bold_webhook_signature(raw_body, signature, "secret-test")

    def test_rejects_mismatched_signature(self):
        raw_body = b'{"event":"SALE_APPROVED"}'
        assert not verify_bold_webhook_signature(raw_body, "deadbeef", "secret-test")

    def test_rejects_missing_signature(self):
        raw_body = b'{"event":"SALE_APPROVED"}'
        assert not verify_bold_webhook_signature(raw_body, None, "secret-test")

    def test_rejects_empty_secret_key_even_if_signature_matches(self):
        """Credencial incompleta (secret_key vacío) no debe aceptar una firma
        calculada con esa misma llave vacía -- sería trivialmente falsificable."""
        raw_body = b'{"event":"SALE_APPROVED"}'
        signature = self._signature(raw_body, "")
        assert not verify_bold_webhook_signature(raw_body, signature, "")
