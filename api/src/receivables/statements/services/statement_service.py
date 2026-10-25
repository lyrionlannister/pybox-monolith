"""Generación y listado de extractos de cuenta (PDF) de un deudor."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import UserDocumentType
from app_platform.countries.repository.country_repository import CountryRepository
from app_platform.documents.models.document_model import DocumentModel
from app_platform.documents.services.document_service import DocumentService
from core.config.logger import logger
from core.security.constants.permissions import PORTFOLIO_CLIENTS
from core.security.policies.security_policies import (
    check_portfolio_org_access,
    get_self_identity,
)
from core.security.services.encrypt_service import encrypt_service
from identity.organizations.repository.organization_repository import (
    OrganizationRepository,
)
from identity.users.enums.user_enums import IdentityVerificationStatus
from identity.users.schemas.user_session_schema import UserSession
from receivables.credits.enums.credit_enums import CREDIT_TYPE_LABELS
from receivables.credits.models.credit_model import CreditModel
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.models.debtor_model import DebtorModel
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payments.enums.payment_enums import PAYMENT_STATUS_LABELS
from receivables.payments.models.payment_model import PaymentModel
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.statements.models.statement_model import StatementModel
from receivables.statements.repository.statement_repository import StatementRepository
from receivables.statements.schemas.statement_schemas import (
    StatementListResponse,
    StatementResponse,
)
from receivables.statements.utils.statement_pdf_builder import (
    StatementCreditLine,
    StatementPaymentLine,
    build_statement_pdf,
)

# Prefijo del dominio en la clave del objeto. El extracto cuelga del deudor, pero lo
# genera el módulo de extractos: reemplaza a `DocumentOwnerScope.DEBTOR` + categoría
# `EXTRACTO`.
STATEMENT_DOCUMENT_STORAGE_DOMAIN = "extracto"


class StatementService:
    def __init__(
        self,
        session: AsyncSession,
        statement_repo: StatementRepository,
        debtor_repo: DebtorRepository,
        portfolio_repo: PortfolioRepository,
        credit_repo: CreditRepository,
        payment_repo: PaymentRepository,
        organization_repo: OrganizationRepository,
    ) -> None:
        self._statement_repo = statement_repo
        self._debtor_repo = debtor_repo
        self._portfolio_repo = portfolio_repo
        self._credit_repo = credit_repo
        self._payment_repo = payment_repo
        self._org_repo = organization_repo
        self._country_repo = CountryRepository(session)
        # El PDF lo guarda el módulo de documentos: acá solo se persiste el id.
        self._document_service = DocumentService(session)

    # ── Lado organización ────────────────────────────────────────────────────

    async def generate(
        self,
        debtor_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        credit_id: Optional[uuid.UUID],
        user_session: UserSession,
    ) -> StatementResponse:
        portfolio = await self._check_portfolio_access(user_session, portfolio_id)
        debtor = await self._require_debtor(debtor_id, portfolio_id)

        credits = await self._resolve_credits(debtor_id, portfolio_id, credit_id)
        if not credits:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "El deudor no tiene créditos activos en este portafolio",
            )

        organization = await self._org_repo.get_by_id(portfolio.organization_id)
        org_name = organization.name if organization else ""
        currency_code = await self._country_repo.get_currency_code(portfolio.country)
        cutoff_date = datetime.now(timezone.utc)

        lines: list[StatementCreditLine] = []
        for credit in credits:
            payments = await self._payment_repo.get_by_credit_id(credit.id)
            lines.append(self._to_credit_line(credit, payments))

        pdf_bytes = build_statement_pdf(
            organization_name=org_name,
            debtor_name=debtor.full_name,
            debtor_document=encrypt_service.decrypt_to_str(debtor.document_number),
            currency_code=currency_code,
            cutoff_date=cutoff_date,
            credits=lines,
        )

        scope_suffix = (
            credits[0].credit_number if credit_id is not None else "consolidado"
        )
        filename = (
            f"extracto_{scope_suffix}_{cutoff_date.strftime('%Y%m%d_%H%M%S')}.pdf"
        )

        # El extracto es un caso 1:1: `extractos.id_documento` ya es una FK real y
        # UNIQUE contra `documentos`, así que no necesita fila en
        # `documentos_deudor`.
        document = await self._document_service.store_generated(
            content=pdf_bytes,
            filename=filename,
            content_type="application/pdf",
            domain=STATEMENT_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(debtor_id),
            uploaded_by=user_session.user_id,
            organization_id=portfolio.organization_id,
        )

        statement = await self._statement_repo.add(
            StatementModel(
                debtor_id=debtor_id,
                portfolio_id=portfolio_id,
                organization_id=portfolio.organization_id,
                credit_id=credit_id,
                cutoff_date=cutoff_date,
                document_id=document.id,
                generated_by=user_session.user_id,
            )
        )
        logger.info(
            "[statements] generado | id=%s deudor=%s portafolio=%s credito=%s por=%s",
            statement.id,
            debtor_id,
            portfolio_id,
            credit_id,
            user_session.user_id,
        )
        return await self._to_response(statement, org_name)

    async def list_for_org(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> StatementListResponse:
        await self._check_portfolio_access(user_session, portfolio_id)
        await self._require_debtor(debtor_id, portfolio_id)
        statements = await self._statement_repo.list_by_debtor_and_portfolio(
            debtor_id, portfolio_id
        )
        return await self._to_list_response(statements)

    async def get_content_for_org(
        self,
        statement_id: uuid.UUID,
        debtor_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        user_session: UserSession,
    ) -> Response:
        await self._check_portfolio_access(user_session, portfolio_id)
        statement = await self._statement_repo.get_by_id_and_portfolio(
            statement_id, portfolio_id
        )
        if statement is None or statement.debtor_id != debtor_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Extracto no encontrado")
        # El ownership ya quedó resuelto arriba (portafolio accesible + extracto de ESE
        # deudor); el id del documento sale de la propia fila autorizada.
        document = await self._require_document(statement.document_id)
        return await self._document_service.to_content_response(
            document, user_session.user_id
        )

    # ── Lado titular (scope SELF) ────────────────────────────────────────────

    async def list_mine(self, user_session: UserSession) -> StatementListResponse:
        debtors = await self._require_self_debtors(user_session)
        statements = await self._statement_repo.list_by_debtor([d.id for d in debtors])
        return await self._to_list_response(statements)

    async def get_content_mine(
        self, statement_id: uuid.UUID, user_session: UserSession
    ) -> Response:
        debtors = await self._require_self_debtors(user_session)
        statement = await self._statement_repo.get_owned_by_debtor(
            statement_id, [d.id for d in debtors]
        )
        if statement is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Extracto no encontrado")
        # Igual que en el lado entidad: el extracto ya se resolvió contra el
        # deudor de la sesión SELF, y el id del documento viene de esa fila.
        document = await self._require_document(statement.document_id)
        return await self._document_service.to_content_response(
            document, user_session.user_id
        )

    # ── Internos ─────────────────────────────────────────────────────────────

    async def _resolve_credits(
        self,
        debtor_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        credit_id: Optional[uuid.UUID],
    ) -> list[CreditModel]:
        if credit_id is not None:
            credit = await self._credit_repo.get_by_id(credit_id)
            if (
                credit is None
                or credit.debtor_id != debtor_id
                or credit.portfolio_id != portfolio_id
            ):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Crédito no encontrado")
            return [credit] if credit.is_active else []

        credits = await self._credit_repo.get_by_debtor_and_portfolio(
            debtor_id, portfolio_id
        )
        return [c for c in credits if c.is_active]

    def _to_credit_line(
        self, credit: CreditModel, payments: list[PaymentModel]
    ) -> StatementCreditLine:
        return StatementCreditLine(
            credit_number=credit.credit_number,
            credit_type_label=CREDIT_TYPE_LABELS.get(
                credit.credit_type, credit.credit_type.value
            ),
            disbursed_date=credit.disbursed_date,
            total_credit_balance=credit.total_credit_balance,
            overdue_principal_balance=credit.overdue_principal_balance,
            days_overdue_at_cutoff=credit.days_overdue_at_cutoff,
            pending_installments=credit.pending_installments,
            overdue_installments=credit.overdue_installments,
            payments=[
                StatementPaymentLine(
                    installment_number=p.installment_number,
                    limit_pay_date=p.limit_pay_date,
                    payment_date=p.payment_date,
                    payment_amount=p.payment_amount,
                    principal_payment=p.principal_payment,
                    total_interest_amount=p.total_interest_amount,
                    status_label=PAYMENT_STATUS_LABELS.get(p.status, p.status.value),
                )
                for p in payments
            ],
        )

    async def _check_portfolio_access(
        self, user_session: UserSession, portfolio_id: uuid.UUID
    ):
        portfolio = await self._portfolio_repo.get_by_id(portfolio_id)
        await check_portfolio_org_access(user_session, portfolio, PORTFOLIO_CLIENTS)
        return portfolio

    async def _require_document(self, document_id: uuid.UUID) -> DocumentModel:
        """Metadatos del PDF del extracto. No revalida pertenencia: el id viene de
        la fila `extractos` que el llamador ya autorizó."""
        document = await self._document_service.get_by_id(document_id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Extracto no encontrado")
        return document

    async def _require_debtor(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID | None = None
    ) -> DebtorModel:
        debtor = await self._debtor_repo.get_by_id(debtor_id)
        if debtor is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Deudor no encontrado")
        if (
            portfolio_id is not None
            and not await self._credit_repo.debtor_belongs_to_portfolio(
                debtor_id, portfolio_id
            )
        ):
            # No se confirma al llamante que el deudor existe fuera de su alcance.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Deudor no encontrado")
        return debtor

    async def _require_self_debtors(
        self, user_session: UserSession
    ) -> list[DebtorModel]:
        document_type, document_number_hash = get_self_identity(user_session)
        try:
            doc_type = UserDocumentType(document_type)
        except ValueError as e:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Tipo de documento no reconocido"
            ) from e
        # Una fila de deudor por empresa: el titular ve los extractos de todas.
        debtors = await self._debtor_repo.list_by_document(
            doc_type, document_number_hash
        )
        if not debtors:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "No encontramos obligaciones a tu nombre"
            )
        # Ser deudor conocido no basta: conocer tipo+número de documento de alguien no
        # es secreto, así que antes de mostrar su información crediticia se exige que el
        # propio titular haya subido su documento de identidad y Atención al Cliente lo
        # haya aprobado (ver IdentityVerificationStatus / OnboardingService).
        if (
            user_session.identity_verification_status
            != IdentityVerificationStatus.APPROVED
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Verificación de identidad pendiente. Sube tu documento de "
                "identidad para acceder a tu información crediticia.",
            )
        return debtors

    async def _to_list_response(
        self, statements: list[StatementModel]
    ) -> StatementListResponse:
        if not statements:
            return StatementListResponse(items=[], total=0)

        org_ids = list({s.organization_id for s in statements})
        orgs = await self._org_repo.get_by_ids(org_ids)
        org_names = {o.id: o.name for o in orgs}

        credit_ids = [s.credit_id for s in statements if s.credit_id is not None]
        credit_numbers: dict[uuid.UUID, str] = {}
        for cid in credit_ids:
            credit = await self._credit_repo.get_by_id(cid)
            if credit is not None:
                credit_numbers[cid] = credit.credit_number

        items = [
            StatementResponse(
                id=s.id,
                debtor_id=s.debtor_id,
                portfolio_id=s.portfolio_id,
                organization_id=s.organization_id,
                organization_name=org_names.get(s.organization_id, ""),
                credit_id=s.credit_id,
                credit_number=credit_numbers.get(s.credit_id) if s.credit_id else None,
                cutoff_date=s.cutoff_date,
                document_id=s.document_id,
                created_at=s.created_at,
            )
            for s in statements
        ]
        return StatementListResponse(items=items, total=len(items))

    async def _to_response(
        self, statement: StatementModel, organization_name: str
    ) -> StatementResponse:
        credit_number: Optional[str] = None
        if statement.credit_id is not None:
            credit = await self._credit_repo.get_by_id(statement.credit_id)
            credit_number = credit.credit_number if credit else None
        return StatementResponse(
            id=statement.id,
            debtor_id=statement.debtor_id,
            portfolio_id=statement.portfolio_id,
            organization_id=statement.organization_id,
            organization_name=organization_name,
            credit_id=statement.credit_id,
            credit_number=credit_number,
            cutoff_date=statement.cutoff_date,
            document_id=statement.document_id,
            created_at=statement.created_at,
        )
