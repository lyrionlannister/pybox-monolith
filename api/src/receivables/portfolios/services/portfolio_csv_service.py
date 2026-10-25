"""Procesamiento de la carga masiva de portafolio (CSV/XLSX)."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import Nationality
from app_platform.countries.repository.country_repository import CountryRepository
from app_platform.documents.enums.document_enums import (
    CSV_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
)
from app_platform.documents.services.document_service import DocumentService
from core.config.logger import logger
from core.security.services.encrypt_service import encrypt_service
from core.tools.config_tools import get_or_default
from receivables.contact_methods.models.contact_method_model import ContactMethodModel
from receivables.contact_methods.repository.contact_method_repository import (
    ContactMethodRepository,
)
from receivables.contact_methods.utils.contact_normalize import normalize_contact_value
from receivables.credits.models.credit_adjustment_model import CreditAdjustmentModel
from receivables.credits.models.credit_model import CreditModel
from receivables.credits.models.uvr_quote_model import UVRQuoteModel
from receivables.credits.repository.credit_adjustment_repository import (
    CreditAdjustmentRepository,
)
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.credits.repository.uvr_quote_repository import UVRQuoteRepository
from receivables.debtors.models.address_model import AddressModel
from receivables.debtors.models.debtor_model import DebtorModel
from receivables.debtors.repository.address_repository import AddressRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payments.models.payment_model import PaymentModel
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.portfolios.constants.portfolio_csv_constants import (
    DEFAULT_PORTFOLIO_CSV_BULK_UPSERT,
    MAX_ERRORS,
    PORTFOLIO_CSV_BULK_CHUNK_SIZE,
    PORTFOLIO_CSV_BULK_UPSERT_ENV_VAR,
)
from receivables.portfolios.enums.portfolio_document_enums import (
    PortfolioDocumentCategory,
)
from receivables.portfolios.models.portfolio_document_model import (
    PortfolioDocumentModel,
)
from receivables.portfolios.models.portfolio_model import PortfolioModel
from receivables.portfolios.repository.portfolio_document_repository import (
    PORTFOLIO_DOCUMENT_STORAGE_DOMAIN,
    PortfolioDocumentRepository,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.schemas.portfolio_csv_schemas import CsvProcessResult
from receivables.portfolios.schemas.portfolio_file_schemas import (
    AddressRowData,
    CreditAdjustmentRowData,
    CreditRowData,
    DebtorRowData,
    PaymentRowData,
    PortfolioRowData,
    UVRQuoteRowData,
)
from receivables.portfolios.utils.portfolio_file_parser import PortfolioFileParser


class PortfolioCsvService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.parser = PortfolioFileParser()
        self.portfolio_repo = PortfolioRepository(session)
        self.country_repo = CountryRepository(session)
        self.debtor_repo = DebtorRepository(session)
        self.address_repo = AddressRepository(session)
        self.contact_method_repo = ContactMethodRepository(session)
        self.credit_repo = CreditRepository(session)
        self.payment_repo = PaymentRepository(session)
        self.uvr_quote_repo = UVRQuoteRepository(session)
        self.credit_adjustment_repo = CreditAdjustmentRepository(session)
        self._document_service = DocumentService(session)
        self._portfolio_document_repo = PortfolioDocumentRepository(session)

    async def _archive_source_file(
        self, portfolio, file_bytes: bytes, filename: str, operation: str
    ):
        """Archiva el archivo fuente de la carga como evidencia de que se cargo.

        Va por `store_generated` y no por la lista blanca de subidas porque el parser
        del modulo ya valido el archivo: esta no es una subida libre de usuario, y
        CSV/XLSX no estan (ni deben estar) entre los tipos que un titular puede subir.
        """
        is_xlsx = filename.lower().endswith(".xlsx")
        ext = "xlsx" if is_xlsx else "csv"
        timestamp = int(datetime.now(timezone.utc).timestamp())
        document = await self._document_service.store_generated(
            content=file_bytes,
            filename=f"{portfolio.id}_{operation}_{timestamp}.{ext}",
            content_type=XLSX_CONTENT_TYPE if is_xlsx else CSV_CONTENT_TYPE,
            domain=PORTFOLIO_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(portfolio.id),
            organization_id=portfolio.organization_id,
        )
        # El enlace al portafolio es una fila propia con FK real, en la misma sesión.
        # `id_organizacion` se denormaliza desde el portafolio ya cargado.
        return await self._portfolio_document_repo.add(
            PortfolioDocumentModel(
                portfolio_id=portfolio.id,
                organization_id=portfolio.organization_id,
                category=PortfolioDocumentCategory.PORTFOLIO_SOURCE,
                document_id=document.id,
            )
        )

    async def process_csv(
        self,
        file_bytes: bytes,
        organization_id: uuid.UUID,
        portfolio_name: str | None = None,
        country: Nationality | None = None,
        filename: str = "",
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> CsvProcessResult:
        logger.info(
            "[process_csv] START | org=%s nombre=%s bytes=%d",
            organization_id,
            portfolio_name,
            len(file_bytes),
        )

        file_data = self.parser.parse(file_bytes, filename)
        logger.info(
            "[process_csv] parsed | filas=%d skipped=%d",
            len(file_data.rows),
            file_data.total_skipped,
        )

        portfolio = await self.portfolio_repo.add(
            PortfolioModel(
                name=portfolio_name or f"Portafolio {organization_id}",
                organization_id=organization_id,
                country=country,
            )
        )
        logger.info("[process_csv] portfolio creado | id=%s", portfolio.id)

        archived = await self._archive_source_file(
            portfolio, file_bytes, filename, "create"
        )
        logger.info(
            "[process_csv] archivo guardado | documento=%s", archived.document_id
        )

        total_rows = len(file_data.rows) + file_data.total_skipped

        titulares_docs = {
            (
                r.debtor.document_type,
                encrypt_service.hash_document(r.debtor.document_number),
            )
            for r in file_data.rows
        }
        codeudores_docs = {
            (
                r.codebtor.document_type,
                encrypt_service.hash_document(r.codebtor.document_number),
            )
            for r in file_data.rows
            if r.codebtor
        }

        phone_prefix = await self.country_repo.get_phone_prefix(portfolio.country)
        processed, errors = await self._process_rows(
            file_data.rows,
            portfolio.id,
            portfolio.organization_id,
            phone_prefix,
            on_progress,
        )

        failed = len(file_data.rows) - processed
        result = CsvProcessResult(
            total_rows=total_rows,
            processed_rows=processed,
            failed_rows=failed,
            portfolio_id=portfolio.id,
            titulares=len(titulares_docs),
            codeudores=len(codeudores_docs),
            creditos=len(file_data.rows),
            clientes_unicos=len(titulares_docs),
            errors=errors,
        )
        logger.info(
            "[process_csv] END | procesados=%d fallidos=%d total=%d",
            processed,
            failed,
            total_rows,
        )
        return result

    # ------------------------------------------------------------------
    # Row processor
    # ------------------------------------------------------------------

    async def _process_row(
        self,
        row: PortfolioRowData,
        portfolio_id: uuid.UUID,
        organization_id: uuid.UUID,
        row_number: int,
        phone_prefix: str | None = None,
    ) -> str | None:
        logger.debug("[_process_row] START | fila=%d", row_number)
        try:
            async with self.session.begin_nested():
                debtor = await self._upsert_debtor(organization_id, row.debtor)
                codebtor = (
                    await self._upsert_debtor(organization_id, row.codebtor)
                    if row.codebtor
                    else None
                )
                await self._upsert_address(debtor.id, row.primary_address)
                if row.secondary_address:
                    await self._upsert_address(debtor.id, row.secondary_address)
                await self._upsert_contact_methods(
                    debtor.id, row.debtor_contacts, phone_prefix
                )
                if codebtor and row.codebtor_contacts:
                    await self._upsert_contact_methods(
                        codebtor.id, row.codebtor_contacts, phone_prefix
                    )
                credit = await self._upsert_credit(
                    row.credit,
                    portfolio_id,
                    debtor.id,
                    codebtor.id if codebtor else None,
                )
                if row.payment:
                    await self._insert_payment(credit.id, row.payment)
                if row.uvr_quote:
                    await self._insert_uvr_quote(credit.id, row.uvr_quote)
                if row.credit_adjustment:
                    await self._insert_credit_adjustment(
                        credit.id, row.credit_adjustment
                    )
        except Exception as exc:
            logger.warning("[_process_row] ERROR | fila=%d error=%s", row_number, exc)
            return f"Fila {row_number} (doc: {row.debtor.document_number}): {exc}"
        logger.debug("[_process_row] END OK | fila=%d", row_number)
        return None

    # ------------------------------------------------------------------
    # Dispatcher: camino secuencial (default) vs. bulk (Fase 4 de la auditoría)
    # ------------------------------------------------------------------

    def _bulk_upsert_enabled(self) -> bool:
        """Lee la env var EN CADA LLAMADA (no cacheada a nivel de módulo/instancia) para
        que el flag se pueda togglear sin redeploy."""
        return (
            get_or_default(
                PORTFOLIO_CSV_BULK_UPSERT_ENV_VAR, DEFAULT_PORTFOLIO_CSV_BULK_UPSERT
            )
            == "true"
        )

    async def _process_rows(
        self,
        rows: list[PortfolioRowData],
        portfolio_id: uuid.UUID,
        organization_id: uuid.UUID,
        phone_prefix: str | None,
        on_progress: Callable[[int, int], Awaitable[None]] | None,
    ) -> tuple[int, list[str]]:
        if self._bulk_upsert_enabled():
            return await self._process_rows_bulk(
                rows, portfolio_id, organization_id, phone_prefix, on_progress
            )
        return await self._process_rows_sequential(
            rows, portfolio_id, organization_id, phone_prefix, on_progress
        )

    async def _process_rows_sequential(
        self,
        rows: list[PortfolioRowData],
        portfolio_id: uuid.UUID,
        organization_id: uuid.UUID,
        phone_prefix: str | None,
        on_progress: Callable[[int, int], Awaitable[None]] | None,
    ) -> tuple[int, list[str]]:
        """Camino histórico: una fila a la vez, cada una en su propio SAVEPOINT."""
        processed = 0
        errors: list[str] = []
        total_to_process = len(rows)
        for idx, row in enumerate(rows, start=1):
            error = await self._process_row(
                row, portfolio_id, organization_id, idx, phone_prefix
            )
            if error:
                if len(errors) < MAX_ERRORS:
                    errors.append(error)
            else:
                processed += 1
            if on_progress and idx % 50 == 0:
                await on_progress(idx, total_to_process)
        return processed, errors

    async def _process_rows_bulk(
        self,
        rows: list[PortfolioRowData],
        portfolio_id: uuid.UUID,
        organization_id: uuid.UUID,
        phone_prefix: str | None,
        on_progress: Callable[[int, int], Awaitable[None]] | None,
    ) -> tuple[int, list[str]]:
        """Precarga + bulk upsert de deudores/créditos por chunk (un solo `INSERT
        ... ON CONFLICT DO UPDATE ... RETURNING` por entidad, en vez de un
        SELECT+INSERT/UPDATE por fila). Direcciones/métodos de contacto/pago/
        cotización UVR/ajuste de crédito siguen resolviéndose fila por fila
        (`_finish_row_after_bulk`) reusando los mismos helpers que el camino
        secuencial -- son operaciones más baratas y ya aceleradas por los índices
        agregados en la Fase 1, así que no valía el riesgo extra de bulk-ificarlas
        también en este mismo cambio.

        Si el bulk de un chunk falla por algo no previsto (p. ej. un dato fuera de
        rango), ESE chunk completo se reprocesa fila por fila con el camino
        secuencial (aislado por SAVEPOINT) -- así nunca se pierde la garantía "una
        fila mala no tumba el archivo", pagando el costo del SAVEPOINT por fila
        solo en el caso excepcional.
        """
        processed = 0
        errors: list[str] = []
        total_to_process = len(rows)

        for chunk_start in range(0, len(rows), PORTFOLIO_CSV_BULK_CHUNK_SIZE):
            chunk = rows[chunk_start : chunk_start + PORTFOLIO_CSV_BULK_CHUNK_SIZE]
            first_row_number = chunk_start + 1

            debtor_id_by_hash: dict[str, uuid.UUID] | None = None
            credit_id_by_number: dict[str, uuid.UUID] | None = None
            try:
                async with self.session.begin_nested():
                    debtor_id_by_hash = await self._bulk_upsert_debtors_chunk(
                        organization_id, chunk
                    )
                    credit_id_by_number = await self._bulk_upsert_credits_chunk(
                        chunk, portfolio_id, debtor_id_by_hash
                    )
            except Exception as exc:
                logger.warning(
                    "[_process_rows_bulk] bulk de chunk falló, reprocesando fila "
                    "por fila | inicio=%d error=%s",
                    first_row_number,
                    exc,
                )
                debtor_id_by_hash = None

            if debtor_id_by_hash is None:
                for offset, row in enumerate(chunk):
                    idx = first_row_number + offset
                    error = await self._process_row(
                        row, portfolio_id, organization_id, idx, phone_prefix
                    )
                    if error:
                        if len(errors) < MAX_ERRORS:
                            errors.append(error)
                    else:
                        processed += 1
                    if on_progress and idx % 50 == 0:
                        await on_progress(idx, total_to_process)
                continue

            for offset, row in enumerate(chunk):
                idx = first_row_number + offset
                error = await self._finish_row_after_bulk(
                    row, idx, debtor_id_by_hash, credit_id_by_number or {}, phone_prefix
                )
                if error:
                    if len(errors) < MAX_ERRORS:
                        errors.append(error)
                else:
                    processed += 1
                if on_progress and idx % 50 == 0:
                    await on_progress(idx, total_to_process)

        return processed, errors

    async def _bulk_upsert_debtors_chunk(
        self, organization_id: uuid.UUID, chunk: list[PortfolioRowData]
    ) -> dict[str, uuid.UUID]:
        """Prepara los datos (titulares + codeudores del chunk) y delega el upsert en
        sí a `DebtorRepository.bulk_upsert_by_document_hash` -- el SQL vive en el
        repository, no en el service. Si un mismo documento aparece varias veces
        (titular repetido entre filas, o la misma persona como titular en una fila y
        codeudor en otra), gana el último valor en el orden de archivo -- mismo criterio
        que aplicaría `_upsert_debtor` llamado secuencialmente fila por fila."""
        debtors_by_hash: dict[str, dict] = {}
        for row in chunk:
            for debtor_data in (d for d in (row.debtor, row.codebtor) if d is not None):
                doc_hash = encrypt_service.hash_document(debtor_data.document_number)
                debtors_by_hash[doc_hash] = {
                    "document_number": encrypt_service.encrypt_to_str(
                        debtor_data.document_number
                    ),
                    "document_number_hash": doc_hash,
                    "full_name": debtor_data.full_name,
                    "document_type": debtor_data.document_type,
                    "debtor_type": debtor_data.debtor_type,
                }
        return await self.debtor_repo.bulk_upsert_by_document_hash(
            organization_id, list(debtors_by_hash.values())
        )

    async def _bulk_upsert_credits_chunk(
        self,
        chunk: list[PortfolioRowData],
        portfolio_id: uuid.UUID,
        debtor_id_by_hash: dict[str, uuid.UUID],
    ) -> dict[str, uuid.UUID]:
        """Mismo criterio que `_bulk_upsert_debtors_chunk`: prepara los datos y delega
        el upsert a `CreditRepository.bulk_upsert_by_credit_number`. `codebtor_id`
        queda `None` cuando la fila no trae codeudor."""
        credits_by_number: dict[str, dict] = {}
        for row in chunk:
            data = row.credit
            debtor_id = debtor_id_by_hash[
                encrypt_service.hash_document(row.debtor.document_number)
            ]
            codebtor_id = (
                debtor_id_by_hash.get(
                    encrypt_service.hash_document(row.codebtor.document_number)
                )
                if row.codebtor
                else None
            )
            credits_by_number[data.credit_number] = {
                "credit_number": data.credit_number,
                "credit_date": data.credit_date,
                "disbursed_date": data.disbursed_date,
                "credit_type": data.credit_type,
                "agreed_interest_rate": data.agreed_interest_rate,
                "charged_effective_annual_rate": data.charged_effective_annual_rate,
                "balance_disbursed": data.balance_disbursed,
                "court_date": data.court_date,
                "initial_term": data.initial_term,
                "total_credit_balance": data.total_credit_balance,
                "overdue_principal_balance": data.overdue_principal_balance,
                "current_interest": data.current_interest,
                "overdue_interest": data.overdue_interest,
                "other_concepts": data.other_concepts,
                "overdue_installments": data.overdue_installments,
                "days_overdue_at_cutoff": data.days_overdue_at_cutoff,
                "amortization_system": data.amortization_system,
                "pending_installments": data.pending_installments,
                "insurance_total": data.insurance_total,
                "commission_accum": data.commission_accum,
                "platform_fee_accum": data.platform_fee_accum,
                "vat_accum": data.vat_accum,
                "subproduct": data.subproduct,
                "uvr_last_quote": data.uvr_last_quote,
                "condonations_accum": data.condonations_accum,
                "portfolio_id": portfolio_id,
                "debtor_id": debtor_id,
                "codebtor_id": codebtor_id,
            }
        return await self.credit_repo.bulk_upsert_by_credit_number(
            list(credits_by_number.values())
        )

    async def _finish_row_after_bulk(
        self,
        row: PortfolioRowData,
        row_number: int,
        debtor_id_by_hash: dict[str, uuid.UUID],
        credit_id_by_number: dict[str, uuid.UUID],
        phone_prefix: str | None,
    ) -> str | None:
        """Resuelve direcciones/contactos/pago/UVR/ajuste de una fila cuyo
        deudor/crédito YA se resolvió en el bulk del chunk -- mismos helpers que
        `_process_row`, sin el SELECT+INSERT/UPDATE de deudor/crédito que ya no
        hace falta repetir."""
        try:
            async with self.session.begin_nested():
                debtor_id = debtor_id_by_hash[
                    encrypt_service.hash_document(row.debtor.document_number)
                ]
                codebtor_id = (
                    debtor_id_by_hash.get(
                        encrypt_service.hash_document(row.codebtor.document_number)
                    )
                    if row.codebtor
                    else None
                )

                await self._upsert_address(debtor_id, row.primary_address)
                if row.secondary_address:
                    await self._upsert_address(debtor_id, row.secondary_address)
                await self._upsert_contact_methods(
                    debtor_id, row.debtor_contacts, phone_prefix
                )
                if codebtor_id and row.codebtor_contacts:
                    await self._upsert_contact_methods(
                        codebtor_id, row.codebtor_contacts, phone_prefix
                    )

                credit_id = credit_id_by_number[row.credit.credit_number]
                if row.payment:
                    await self._insert_payment(credit_id, row.payment)
                if row.uvr_quote:
                    await self._insert_uvr_quote(credit_id, row.uvr_quote)
                if row.credit_adjustment:
                    await self._insert_credit_adjustment(
                        credit_id, row.credit_adjustment
                    )
        except Exception as exc:
            logger.warning(
                "[_finish_row_after_bulk] ERROR | fila=%d error=%s", row_number, exc
            )
            return f"Fila {row_number} (doc: {row.debtor.document_number}): {exc}"
        return None

    # ------------------------------------------------------------------
    # Upsert helpers
    # ------------------------------------------------------------------

    async def _upsert_debtor(
        self, organization_id: uuid.UUID, data: DebtorRowData
    ) -> DebtorModel:
        logger.debug("[_upsert_debtor] START")
        doc_hash = encrypt_service.hash_document(data.document_number)
        existing = await self.debtor_repo.get_by_document_number(
            organization_id, doc_hash
        )
        if existing:
            existing.full_name = data.full_name
            existing.document_type = data.document_type
            result = await self.debtor_repo.update(existing)
            logger.debug("[_upsert_debtor] END updated | id=%d", result.id)
            return result
        result = await self.debtor_repo.add(
            DebtorModel(
                organization_id=organization_id,
                document_number=encrypt_service.encrypt_to_str(data.document_number),
                document_number_hash=doc_hash,
                full_name=data.full_name,
                document_type=data.document_type,
                debtor_type=data.debtor_type,
            )
        )
        logger.debug("[_upsert_debtor] END created | id=%d", result.id)
        return result

    async def _upsert_address(self, debtor_id: uuid.UUID, data: AddressRowData) -> None:
        logger.debug(
            "[_upsert_address] START | debtor_id=%d type=%s",
            debtor_id,
            data.address_type,
        )
        existing_list = await self.address_repo.get_by_debtor_id(debtor_id)
        existing = next(
            (a for a in existing_list if a.address_type == data.address_type), None
        )
        if existing:
            existing.address = data.address
            existing.city = data.city
            existing.state = data.state
            existing.country = data.country
            await self.address_repo.update(existing)
        else:
            await self.address_repo.add(
                AddressModel(
                    debtor_id=debtor_id,
                    address=data.address,
                    city=data.city,
                    state=data.state,
                    country=data.country,
                    address_type=data.address_type,
                )
            )

    async def _upsert_contact_methods(
        self, debtor_id: uuid.UUID, contacts: list, phone_prefix: str | None = None
    ) -> None:
        logger.debug(
            "[_upsert_contact_methods] START | debtor_id=%d count=%d",
            debtor_id,
            len(contacts),
        )
        existing_list = await self.contact_method_repo.get_by_debtor_id(debtor_id)
        existing_by_type = {c.contact_type: c for c in existing_list}
        for contact_data in contacts:
            # Normalizar antes de insertar: EMAIL en minúsculas; PHONE con
            # indicativo de país (según el país del portafolio). Así el dato
            # importado queda comparable con el autogestionado y verificado por
            # el titular.
            value = normalize_contact_value(
                contact_data.contact_type, contact_data.contact_value, phone_prefix
            )
            if contact_data.contact_type in existing_by_type:
                record = existing_by_type[contact_data.contact_type]
                record.contact_value = value
                await self.contact_method_repo.update(record)
            else:
                await self.contact_method_repo.add(
                    ContactMethodModel(
                        debtor_id=debtor_id,
                        contact_type=contact_data.contact_type,
                        contact_value=value,
                    )
                )
        logger.debug("[_upsert_contact_methods] END | debtor_id=%d", debtor_id)

    async def _upsert_credit(
        self,
        data: CreditRowData,
        portfolio_id: uuid.UUID,
        debtor_id: uuid.UUID,
        codebtor_id: uuid.UUID | None,
    ) -> CreditModel:
        logger.debug(
            "[_upsert_credit] START | credit_number=%s debtor_id=%d",
            data.credit_number,
            debtor_id,
        )
        fields = {
            "credit_number": data.credit_number,
            "credit_date": data.credit_date,
            "disbursed_date": data.disbursed_date,
            "credit_type": data.credit_type,
            "agreed_interest_rate": data.agreed_interest_rate,
            "charged_effective_annual_rate": data.charged_effective_annual_rate,
            "balance_disbursed": data.balance_disbursed,
            "court_date": data.court_date,
            "initial_term": data.initial_term,
            "total_credit_balance": data.total_credit_balance,
            "overdue_principal_balance": data.overdue_principal_balance,
            "current_interest": data.current_interest,
            "overdue_interest": data.overdue_interest,
            "other_concepts": data.other_concepts,
            "overdue_installments": data.overdue_installments,
            "days_overdue_at_cutoff": data.days_overdue_at_cutoff,
            "amortization_system": data.amortization_system,
            "pending_installments": data.pending_installments,
            "insurance_total": data.insurance_total,
            "commission_accum": data.commission_accum,
            "platform_fee_accum": data.platform_fee_accum,
            "vat_accum": data.vat_accum,
            "subproduct": data.subproduct,
            "uvr_last_quote": data.uvr_last_quote,
            "condonations_accum": data.condonations_accum,
            "portfolio_id": portfolio_id,
            "debtor_id": debtor_id,
            "codebtor_id": codebtor_id,
        }
        existing = await self.credit_repo.get_by_credit_number(
            data.credit_number, portfolio_id
        )
        if existing:
            for attr, val in fields.items():
                setattr(existing, attr, val)
            result = await self.credit_repo.update(existing)
            logger.debug("[_upsert_credit] END updated | id=%d", result.id)
            return result
        result = await self.credit_repo.add(CreditModel(**fields))
        logger.debug("[_upsert_credit] END created | id=%d", result.id)
        return result

    async def _insert_payment(self, credit_id: uuid.UUID, data: PaymentRowData) -> None:
        logger.debug("[_insert_payment] START | credit_id=%d", credit_id)
        insurances_total = data.life_insurance_charge + data.vehicle_insurance_charge
        total_interest = data.current_interest_amount + data.overdue_interest_amount
        await self.payment_repo.add(
            PaymentModel(
                credit_id=credit_id,
                payment_date=data.payment_date,
                limit_pay_date=data.limit_pay_date,
                payment_amount=data.payment_amount,
                installment_number=data.installment_number,
                principal_payment=data.principal_payment,
                current_interest_amount=data.current_interest_amount,
                overdue_interest_amount=data.overdue_interest_amount,
                life_insurance_charge=data.life_insurance_charge,
                vehicle_insurance_charge=data.vehicle_insurance_charge,
                insurances_total=insurances_total,
                other_charges=data.other_charges,
                total_interest_amount=total_interest,
                other_concepts_amount=Decimal("0"),
                vat=data.vat,
                commission_amount=data.commission_amount,
                platform_fee=data.platform_fee,
                condonation_amount=Decimal("0"),
                discount_amount=Decimal("0"),
            )
        )
        logger.debug("[_insert_payment] END | credit_id=%d", credit_id)

    async def _insert_uvr_quote(
        self, credit_id: uuid.UUID, data: UVRQuoteRowData
    ) -> None:
        logger.debug("[_insert_uvr_quote] START | credit_id=%d", credit_id)
        await self.uvr_quote_repo.add(
            UVRQuoteModel(
                credit_id=credit_id,
                quote_value=data.quote_value,
                quote_date=data.quote_date,
            )
        )
        logger.debug("[_insert_uvr_quote] END | credit_id=%d", credit_id)

    async def _insert_credit_adjustment(
        self, credit_id: uuid.UUID, data: CreditAdjustmentRowData
    ) -> None:
        logger.debug(
            "[_insert_credit_adjustment] START | credit_id=%d type=%s",
            credit_id,
            data.adjustment_type,
        )
        await self.credit_adjustment_repo.add(
            CreditAdjustmentModel(
                credit_id=credit_id,
                adjustment_type=data.adjustment_type,
                adjustment_amount=data.adjustment_amount,
                applied_date=data.applied_date,
            )
        )
        logger.debug("[_insert_credit_adjustment] END | credit_id=%d", credit_id)

    # ------------------------------------------------------------------
    # Append mode — agrega datos a portafolio existente (upsert)
    # ------------------------------------------------------------------

    async def append_csv(
        self,
        portfolio_id: uuid.UUID,
        file_bytes: bytes,
        filename: str = "",
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> CsvProcessResult:
        logger.info(
            "[append_csv] START | portfolio=%s bytes=%d", portfolio_id, len(file_bytes)
        )
        portfolio = await self.portfolio_repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portafolio {portfolio_id} no encontrado")

        file_data = self.parser.parse(file_bytes, filename)
        logger.info(
            "[append_csv] parsed | filas=%d skipped=%d",
            len(file_data.rows),
            file_data.total_skipped,
        )

        await self._archive_source_file(portfolio, file_bytes, filename, "append")

        titulares_docs = {
            (
                r.debtor.document_type,
                encrypt_service.hash_document(r.debtor.document_number),
            )
            for r in file_data.rows
        }
        codeudores_docs = {
            (
                r.codebtor.document_type,
                encrypt_service.hash_document(r.codebtor.document_number),
            )
            for r in file_data.rows
            if r.codebtor
        }

        total_rows = len(file_data.rows) + file_data.total_skipped

        phone_prefix = await self.country_repo.get_phone_prefix(portfolio.country)
        processed, errors = await self._process_rows(
            file_data.rows,
            portfolio.id,
            portfolio.organization_id,
            phone_prefix,
            on_progress,
        )

        failed = len(file_data.rows) - processed
        result = CsvProcessResult(
            total_rows=total_rows,
            processed_rows=processed,
            failed_rows=failed,
            portfolio_id=portfolio.id,
            titulares=len(titulares_docs),
            codeudores=len(codeudores_docs),
            creditos=len(file_data.rows),
            clientes_unicos=len(titulares_docs),
            errors=errors,
        )
        logger.info("[append_csv] END | procesados=%d fallidos=%d", processed, failed)
        return result

    # ------------------------------------------------------------------
    # Update mode — reemplaza todos los créditos del portafolio
    # ------------------------------------------------------------------

    async def update_csv(
        self,
        portfolio_id: uuid.UUID,
        file_bytes: bytes,
        filename: str = "",
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> CsvProcessResult:
        logger.info(
            "[update_csv] START | portfolio=%s bytes=%d", portfolio_id, len(file_bytes)
        )
        portfolio = await self.portfolio_repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise ValueError(f"Portafolio {portfolio_id} no encontrado")

        # Parsear primero: si el archivo viene mal formado, esto lanza y no debe
        # borrarse ningún crédito existente (ver update_and_notify, que atrapa
        # excepciones sin relanzar — el orden es lo único que evita perder datos).
        file_data = self.parser.parse(file_bytes, filename)
        logger.info(
            "[update_csv] parsed | filas=%d skipped=%d",
            len(file_data.rows),
            file_data.total_skipped,
        )

        existing_credits = await self.credit_repo.get_by_portfolio_id(portfolio_id)
        logger.info(
            "[update_csv] eliminando %d créditos existentes", len(existing_credits)
        )
        await self.credit_repo.soft_delete_by_portfolios(
            [portfolio_id], datetime.now(timezone.utc)
        )

        await self._archive_source_file(portfolio, file_bytes, filename, "update")

        titulares_docs = {
            (
                r.debtor.document_type,
                encrypt_service.hash_document(r.debtor.document_number),
            )
            for r in file_data.rows
        }
        codeudores_docs = {
            (
                r.codebtor.document_type,
                encrypt_service.hash_document(r.codebtor.document_number),
            )
            for r in file_data.rows
            if r.codebtor
        }

        total_rows = len(file_data.rows) + file_data.total_skipped

        phone_prefix = await self.country_repo.get_phone_prefix(portfolio.country)
        processed, errors = await self._process_rows(
            file_data.rows,
            portfolio.id,
            portfolio.organization_id,
            phone_prefix,
            on_progress,
        )

        failed = len(file_data.rows) - processed
        result = CsvProcessResult(
            total_rows=total_rows,
            processed_rows=processed,
            failed_rows=failed,
            portfolio_id=portfolio.id,
            titulares=len(titulares_docs),
            codeudores=len(codeudores_docs),
            creditos=len(file_data.rows),
            clientes_unicos=len(titulares_docs),
            errors=errors,
        )
        logger.info("[update_csv] END | procesados=%d fallidos=%d", processed, failed)
        return result
