"""Generación de referencias únicas para transacciones de cobro."""

import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal


def to_base36(value: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    chars = []
    while value:
        value, rem = divmod(value, 36)
        chars.append(digits[rem])
    return "".join(reversed(chars)).upper()


def build_payment_reference(payment_id: uuid.UUID, attempt_number: int) -> str:
    """PAG-{shortId}-{numeroIntento}-{timestamp}, <= 60 caracteres (limite de Wompi para
    `reference`)."""
    short_id = payment_id.hex[:8].upper()
    ts = to_base36(int(datetime.now(timezone.utc).timestamp() * 1000))
    return f"PAG-{short_id}-{attempt_number}-{ts}"[:60]


def to_amount_in_cents(amount: Decimal) -> int:
    """Wompi trabaja en centavos COP enteros (`amount_in_cents`)."""
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_cents_to_whole_currency_cents(amount_in_cents: int) -> int:
    """Bold/ePayco/PayU facturan en pesos enteros, no en centavos: redondea
    `amount_in_cents` al peso más cercano (HALF_UP, igual criterio que
    `to_amount_in_cents`) y lo devuelve ya en centavos (múltiplo de 100), para que
    el monto cobrado real y el monto esperado registrado coincidan."""
    whole_units = (Decimal(amount_in_cents) / 100).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(whole_units * 100)
