"""Resuelve qué pasarela de facturación usar según el país de la organización."""

from sqlalchemy.ext.asyncio import AsyncSession

from billing.gateways.base import PaymentGateway
from billing.gateways.bold.bold_gateway import BoldGateway
from billing.gateways.mercadopago.mercadopago_gateway import MercadoPagoGateway
from billing.gateways.unsupported_gateway import UnsupportedGateway
from billing.mercadopago.utils.mercadopago_credentials import (
    resolve_credentials_for_country,
)

_bold = BoldGateway()
_unsupported = UnsupportedGateway()

# Países que operan con Mercado Pago: sus credenciales se resuelven de DB (cifradas) en
# runtime y se arma el gateway al vuelo — ya no en import-time. Bold solo opera en
# Colombia; AR/PE/VE no tienen pasarela propia (no se comparte la cuenta de MX, eso
# liquidaría en la moneda/cuenta equivocada).
_MERCADOPAGO_COUNTRIES = {"MX"}
_UNSUPPORTED_COUNTRIES = {"AR", "PE", "VE"}


class PaymentGatewayResolver:
    async def get_for_country(
        self, country: str | None, session: AsyncSession
    ) -> PaymentGateway:
        if country is None or country == "CO":
            return _bold
        if country in _MERCADOPAGO_COUNTRIES:
            credentials = await resolve_credentials_for_country(session, country)
            if credentials is None:
                return _unsupported
            return MercadoPagoGateway(credentials)
        # País no contemplado en ninguna de las listas de arriba (ej. se agregó a
        # `Nationality` sin actualizar este resolver): falla explícito en vez de
        # caer a Bold (exclusiva de Colombia) por defecto, que cobraría en la
        # cuenta/moneda equivocada.
        return _unsupported
