"""Autogestión de métodos de contacto de un deudor (verificación por documento)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import UserDocumentType
from app_platform.countries.repository.country_repository import CountryRepository
from core.config.logger import logger
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType
from receivables.contact_methods.models.contact_method_model import ContactMethodModel
from receivables.contact_methods.repository.contact_method_repository import (
    ContactMethodRepository,
)
from receivables.contact_methods.utils.contact_normalize import normalize_contact_value
from receivables.debtors.repository.debtor_repository import DebtorRepository


class SelfServiceContactService:
    """Propaga a las orgs el correo/teléfono verificado por el propio titular (USER
    SELF).

    El deudor es único global (por ``numero_documento_hash``), así que agregar una
    fila de ``metodos_contacto`` al deudor lo hace visible a todas las orgs donde
    tiene créditos.
    """

    def __init__(
        self,
        session: AsyncSession,
        debtor_repo: DebtorRepository,
        contact_repo: ContactMethodRepository,
    ) -> None:
        self._debtor_repo = debtor_repo
        self._contact_repo = contact_repo
        self._country_repo = CountryRepository(session)

    async def register_verified_contact(
        self,
        document_type: UserDocumentType,
        document_number_hash: str,
        contact_type: ContactMethodType,
        contact_value: str | None,
        country_code: str | None,
    ) -> bool:
        """Registra el valor verificado como método de contacto del deudor, si difiere.

        Devuelve ``True`` si se creó una fila nueva; ``False`` si no había deudor, el
        valor estaba vacío o ya existía (comparado normalizado; PHONE siempre con
        prefijo de país).
        """
        if not contact_value:
            return False

        # El titular puede figurar como deudor en varias empresas (una fila por
        # empresa): el contacto verificado se registra en cada una, porque cada
        # empresa tiene su propia copia de los datos de contacto.
        debtors = await self._debtor_repo.list_by_document(
            document_type, document_number_hash
        )
        if not debtors:
            return False

        country_prefix = (
            await self._country_repo.get_phone_prefix(country_code)
            if contact_type == ContactMethodType.PHONE
            else None
        )
        normalized = normalize_contact_value(
            contact_type, contact_value, country_prefix
        )
        if not normalized:
            return False

        existing_by_debtor: dict[uuid.UUID, set[str | None]] = {}
        all_contacts = await self._contact_repo.get_by_debtor_ids(
            [d.id for d in debtors]
        )
        for c in all_contacts:
            if c.contact_type == contact_type:
                existing_by_debtor.setdefault(c.debtor_id, set()).add(
                    normalize_contact_value(
                        contact_type, c.contact_value, country_prefix
                    )
                )

        created = False
        for debtor in debtors:
            if normalized in existing_by_debtor.get(debtor.id, set()):
                continue

            await self._contact_repo.add(
                ContactMethodModel(
                    debtor_id=debtor.id,
                    contact_type=contact_type,
                    contact_value=normalized,
                )
            )
            logger.info(
                "[self_service_contact] contacto verificado registrado | "
                "debtor_id=%s tipo=%s",
                debtor.id,
                contact_type.value,
            )
            created = True
        return created
