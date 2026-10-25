"""Crea o actualiza los canales de mensajería base (SMS, email, IVR, WhatsApp)."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from messaging.channels.enums.channel_enums import ChannelName, Currency
from messaging.channels.models.channel_model import ChannelModel

_CHANNELS: list[tuple[ChannelName, str, Currency, str, str]] = [
    (
        ChannelName.SMS,
        "SMS",
        Currency.USD,
        "0.25",
        "Canal para envío de SMS masivo a través de API.",
    ),
    (
        ChannelName.EMAIL,
        "Email",
        Currency.USD,
        "0.35",
        "Canal para envío de EMAIL masivo a través de API.",
    ),
    (
        ChannelName.WHATSAPP,
        "WhatsApp",
        Currency.USD,
        "0.50",
        "Canal para envío de WHATSAPP masivo a través de API.",
    ),
    (ChannelName.CALL, "Llamada", Currency.USD, "0.50", "Canal para llamadas de voz."),
    (
        ChannelName.CALL_IA,
        "Llamada IA",
        Currency.USD,
        "0.50",
        "Canal para llamadas de voz automatizadas con IA.",
    ),
]


async def seed_channels(session: AsyncSession) -> None:
    existing = {
        row[0] for row in (await session.execute(select(ChannelModel.name))).all()
    }
    new_channels = []
    for name, label, currency, unit_price, description in _CHANNELS:
        if name not in existing:
            new_channels.append(
                ChannelModel(
                    name=name,
                    label=label,
                    currency=currency,
                    unit_price=unit_price,
                    description=description,
                )
            )
        else:
            await session.execute(
                update(ChannelModel)
                .where(ChannelModel.name == name)
                .values(label=label)
            )
    if new_channels:
        session.add_all(new_channels)
