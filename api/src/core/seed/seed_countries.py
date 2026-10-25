"""Crea o actualiza el catálogo de países soportados y sus tipos de documento."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import (
    DOCUMENT_TYPE_LABELS,
    DOCUMENTS_BY_NATIONALITY,
    NATIONALITY_CURRENCY_CODE,
    NATIONALITY_NAMES,
    NATIONALITY_PHONE_PREFIX,
    NATIONALITY_TIMEZONE,
    ORG_FISCAL_DOCUMENT_BY_NATIONALITY,
    ORG_MERCANTILE_DOCUMENT_BY_NATIONALITY,
    DocumentScope,
    Nationality,
)
from app_platform.countries.models.country_document_type_model import (
    CountryDocumentTypeModel,
)
from app_platform.countries.models.country_model import CountryModel
from app_platform.countries.models.document_type_model import DocumentTypeModel
from core.config.logger import logger

_FLAG_URL = "https://flagcdn.com/{code}.svg"


def _document_labels() -> dict[str, str]:
    """Etiqueta legible por código de documento, desde DOCUMENT_TYPE_LABELS (fuente de
    verdad). Si algún código no estuviera mapeado, cae al propio código."""
    labels: dict[str, str] = {}
    codes: set[str] = set()
    for docs in DOCUMENTS_BY_NATIONALITY.values():
        codes.update(doc.value for doc in docs)
    codes.update(fiscal.value for fiscal in ORG_FISCAL_DOCUMENT_BY_NATIONALITY.values())
    codes.update(
        mercantile.value
        for mercantile in ORG_MERCANTILE_DOCUMENT_BY_NATIONALITY.values()
    )
    for code in codes:
        labels[code] = DOCUMENT_TYPE_LABELS.get(code, code)
    return labels


def _country_document_rows() -> list[tuple[str, str, DocumentScope]]:
    rows: list[tuple[str, str, DocumentScope]] = []
    for nationality in Nationality:
        for doc in DOCUMENTS_BY_NATIONALITY.get(nationality, []):
            rows.append((nationality.value, doc.value, DocumentScope.PERSON))
        fiscal = ORG_FISCAL_DOCUMENT_BY_NATIONALITY.get(nationality)
        if fiscal is not None:
            rows.append((nationality.value, fiscal.value, DocumentScope.ORG_FISCAL))
        mercantile = ORG_MERCANTILE_DOCUMENT_BY_NATIONALITY.get(nationality)
        if mercantile is not None:
            rows.append(
                (nationality.value, mercantile.value, DocumentScope.ORG_MERCANTILE)
            )
    return rows


async def seed_countries(session: AsyncSession) -> None:
    # 1. Catálogo de países
    existing_countries = {
        row[0] for row in (await session.execute(select(CountryModel.code))).all()
    }
    for nationality in Nationality:
        if nationality.value in existing_countries:
            continue
        session.add(
            CountryModel(
                code=nationality.value,
                name=NATIONALITY_NAMES[nationality],
                phone_prefix=NATIONALITY_PHONE_PREFIX[nationality],
                timezone=NATIONALITY_TIMEZONE[nationality],
                currency_code=NATIONALITY_CURRENCY_CODE[nationality],
                flag_url=_FLAG_URL.format(code=nationality.value.lower()),
            )
        )

    # 2. Catálogo de tipos de documento (upsert de la etiqueta: si el código ya existe
    #    se actualiza su label, para que cambios en DOCUMENT_TYPE_LABELS se reflejen sin
    #    borrar la DB).
    existing_docs = {
        row[0] for row in (await session.execute(select(DocumentTypeModel.code))).all()
    }
    for code, label in _document_labels().items():
        if code not in existing_docs:
            session.add(DocumentTypeModel(code=code, label=label))
        else:
            await session.execute(
                update(DocumentTypeModel)
                .where(DocumentTypeModel.code == code)
                .values(label=label)
            )

    await session.flush()

    # 3. Relación país ↔ documento ↔ alcance
    existing_links = {
        (row[0], row[1], row[2])
        for row in (
            await session.execute(
                select(
                    CountryDocumentTypeModel.country_code,
                    CountryDocumentTypeModel.document_code,
                    CountryDocumentTypeModel.scope,
                )
            )
        ).all()
    }
    for country_code, document_code, scope in _country_document_rows():
        if (country_code, document_code, scope) not in existing_links:
            session.add(
                CountryDocumentTypeModel(
                    country_code=country_code,
                    document_code=document_code,
                    scope=scope,
                )
            )

    logger.info("[seed] countries_seeded | countries=%d", len(Nationality))
