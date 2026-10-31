"""`PaymentGatewayResolver.get_for_country` -- un país no contemplado en ninguna de
las listas debe quedar sin pasarela (UnsupportedGateway), no caer a Bold (exclusiva
de Colombia) por defecto."""

from billing.gateways.resolver import PaymentGatewayResolver


class TestGetForCountry:
    async def test_colombia_uses_bold(self):
        gateway = await PaymentGatewayResolver().get_for_country("CO", session=None)
        assert gateway.name == "BOLD"

    async def test_none_defaults_to_bold(self):
        gateway = await PaymentGatewayResolver().get_for_country(None, session=None)
        assert gateway.name == "BOLD"

    async def test_known_unsupported_country_returns_unsupported(self):
        gateway = await PaymentGatewayResolver().get_for_country("AR", session=None)
        assert gateway.name == "UNSUPPORTED"

    async def test_unknown_country_returns_unsupported_not_bold(self):
        """País nuevo que se agregó a Nationality sin actualizar este resolver:
        debe fallar explícito, no cobrar en la cuenta/moneda de Bold por error."""
        gateway = await PaymentGatewayResolver().get_for_country("ZZ", session=None)
        assert gateway.name == "UNSUPPORTED"
