"""Alta, edición y consulta de deudores, direcciones y créditos asociados."""

import uuid

from fastapi import HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.repository.country_repository import CountryRepository
from app_platform.documents.services.document_service import DocumentService
from core.config.logger import logger
from core.security.constants.permissions import PORTFOLIO_CLIENTS
from core.security.policies.security_policies import (
    check_portfolio_org_access,
    require_permission,
)
from core.security.services.encrypt_service import encrypt_service
from identity.users.schemas.user_session_schema import UserSession
from receivables.contact_methods.models.contact_method_model import ContactMethodModel
from receivables.contact_methods.repository.contact_method_repository import (
    ContactMethodRepository,
)
from receivables.contact_methods.utils.contact_normalize import normalize_contact_value
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.models.address_model import AddressModel
from receivables.debtors.models.debtor_model import DebtorModel
from receivables.debtors.repository.address_repository import AddressRepository
from receivables.debtors.repository.debtor_document_repository import (
    DebtorDocumentRepository,
)
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.debtors.schemas.debtor_document_schemas import (
    DebtorDocumentListResponse,
)
from receivables.debtors.schemas.debtor_schemas import (
    AddressResponse,
    ContactMethodResponse,
    CreateAddressRequest,
    CreateContactMethodRequest,
    CreateDebtorRequest,
    DebtorCreditResponse,
    DebtorCreditWithInstallmentsResponse,
    DebtorDetailResponse,
    DebtorInstallmentResponse,
    DebtorListResponse,
    DebtorResponse,
    RelatedContactsResponse,
)
from receivables.debtors.services.debtor_document_service import DebtorDocumentService
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository


class DebtorService:
    def __init__(
        self,
        session: AsyncSession,
        debtor_repo: DebtorRepository,
        address_repo: AddressRepository,
        contact_repo: ContactMethodRepository,
        portfolio_repo: PortfolioRepository,
        credit_repo: CreditRepository,
        payment_repo: PaymentRepository,
        document_repo: DebtorDocumentRepository,
    ) -> None:
        self._country_repo = CountryRepository(session)
        self._document_service = DocumentService(session)
        self.debtor_repo = debtor_repo
        self.address_repo = address_repo
        self.contact_repo = contact_repo
        self.portfolio_repo = portfolio_repo
        self.credit_repo = credit_repo
        self.payment_repo = payment_repo
        self.document_repo = document_repo

    async def get_debtor(
        self,
        debtor_id: uuid.UUID,
        user_session: UserSession,
        portfolio_id: uuid.UUID | None,
    ) -> DebtorDetailResponse:
        if portfolio_id is not None:
            await self._check_portfolio_access(user_session, portfolio_id)
        elif not user_session.is_global:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "portfolioId es requerido")
        debtor = await self._require_debtor(debtor_id, portfolio_id)
        addresses = await self.address_repo.get_by_debtor_id(debtor_id)
        contacts = await self.contact_repo.get_by_debtor_id(debtor_id)
        return self._to_detail(debtor, addresses, contacts)

    async def list_debtors(
        self,
        user_session: UserSession,
        page: int,
        page_size: int,
        portfolio_id: uuid.UUID | None,
        q: str | None = None,
        sort_by: str = "fullName",
        sort_order: str = "asc",
    ) -> DebtorListResponse:
        if portfolio_id is not None:
            await self._check_portfolio_access(user_session, portfolio_id)
        elif not user_session.is_global:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "portfolioId es requerido")

        items, total = await self.debtor_repo.list_paginated(
            page=page,
            page_size=page_size,
            q=q,
            portfolio_id=portfolio_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return DebtorListResponse(
            items=[self._to_response(d) for d in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_related_contacts(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> RelatedContactsResponse:
        await self._check_portfolio_access(user_session, portfolio_id)
        debtor = await self._require_debtor(debtor_id, portfolio_id)

        # Solo créditos donde el deudor es titular — igual que pybox
        related_ids = await self.credit_repo.get_codebtor_ids(debtor_id, portfolio_id)

        primary_addresses = await self.address_repo.get_by_debtor_id(debtor_id)
        primary_contacts = await self.contact_repo.get_by_debtor_id(debtor_id)

        related_debtors = {
            d.id: d for d in await self.debtor_repo.get_by_ids(related_ids)
        }
        related_addresses: dict[uuid.UUID, list] = {}
        for a in await self.address_repo.get_by_debtor_ids(related_ids):
            related_addresses.setdefault(a.debtor_id, []).append(a)
        related_contacts: dict[uuid.UUID, list] = {}
        for c in await self.contact_repo.get_by_debtor_ids(related_ids):
            related_contacts.setdefault(c.debtor_id, []).append(c)

        codebtors = []
        for rid in related_ids:
            rel = related_debtors.get(rid)
            if rel is None:
                continue
            codebtors.append(
                self._to_detail(
                    rel, related_addresses.get(rid, []), related_contacts.get(rid, [])
                )
            )

        return RelatedContactsResponse(
            debtor=self._to_detail(debtor, primary_addresses, primary_contacts),
            codebtors=codebtors,
        )

    async def get_debtor_credits(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> list[DebtorCreditResponse]:
        await self._check_portfolio_access(user_session, portfolio_id)
        await self._require_debtor(debtor_id, portfolio_id)
        portfolio = await self.portfolio_repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Portafolio no encontrado")
        currency_code = await self._country_repo.get_currency_code(portfolio.country)
        credits = await self.credit_repo.get_by_debtor_and_portfolio(
            debtor_id, portfolio_id
        )
        return [
            DebtorCreditResponse(
                id=c.id,
                credit_number=c.credit_number,
                credit_type=c.credit_type,
                disbursed_date=c.disbursed_date,
                total_credit_balance=float(c.total_credit_balance),
                overdue_principal_balance=float(c.overdue_principal_balance),
                days_overdue_at_cutoff=c.days_overdue_at_cutoff,
                overdue_installments=c.overdue_installments,
                pending_installments=c.pending_installments,
                currency_code=currency_code,
            )
            for c in credits
        ]

    async def get_debtor_credits_with_installments(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> list[DebtorCreditWithInstallmentsResponse]:
        await self._check_portfolio_access(user_session, portfolio_id)
        await self._require_debtor(debtor_id, portfolio_id)
        portfolio = await self.portfolio_repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Portafolio no encontrado")
        currency_code = await self._country_repo.get_currency_code(portfolio.country)
        credits = await self.credit_repo.get_by_debtor_and_portfolio(
            debtor_id, portfolio_id
        )
        installments_by_credit: dict[uuid.UUID, list] = {}
        for p in await self.payment_repo.get_by_credit_ids([c.id for c in credits]):
            installments_by_credit.setdefault(p.credit_id, []).append(p)

        result = []
        for c in credits:
            installments = installments_by_credit.get(c.id, [])
            result.append(
                DebtorCreditWithInstallmentsResponse(
                    credit=DebtorCreditResponse(
                        id=c.id,
                        credit_number=c.credit_number,
                        credit_type=c.credit_type,
                        disbursed_date=c.disbursed_date,
                        total_credit_balance=float(c.total_credit_balance),
                        overdue_principal_balance=float(c.overdue_principal_balance),
                        days_overdue_at_cutoff=c.days_overdue_at_cutoff,
                        overdue_installments=c.overdue_installments,
                        pending_installments=c.pending_installments,
                        currency_code=currency_code,
                    ),
                    installments=[
                        DebtorInstallmentResponse(
                            id=p.id,
                            installment_number=p.installment_number,
                            limit_pay_date=p.limit_pay_date,
                            payment_date=p.payment_date,
                            payment_amount=float(p.payment_amount),
                            principal_payment=float(p.principal_payment),
                            current_interest_amount=float(p.current_interest_amount),
                            overdue_interest_amount=float(p.overdue_interest_amount),
                            total_interest_amount=float(p.total_interest_amount),
                            other_charges=float(p.other_charges),
                        )
                        for p in installments
                    ],
                )
            )
        return result

    async def get_debtor_documents(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID, user_session: UserSession
    ) -> DebtorDocumentListResponse:
        # Cadena completa: portafolio accesible → deudor pertenece a ese portafolio →
        # documentos que cuelgan de ese deudor (`documentos_deudor.id_deudor`).
        await self._check_portfolio_access(user_session, portfolio_id)
        await self._require_debtor(debtor_id, portfolio_id)
        rows = await self.document_repo.list_by_debtor(debtor_id)
        return DebtorDocumentService.to_list_response(rows)

    async def get_debtor_document_content(
        self,
        debtor_id: uuid.UUID,
        document_id: uuid.UUID,
        portfolio_id: uuid.UUID,
        user_session: UserSession,
    ) -> Response:
        await self._check_portfolio_access(user_session, portfolio_id)
        await self._require_debtor(debtor_id, portfolio_id)
        # Último eslabón: el documento tiene que colgar de ESE deudor. Si no, 404
        # — no se le confirma al llamante que existe fuera de su alcance.
        row = await self.document_repo.get_owned(debtor_id, document_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado")
        return await self._document_service.to_content_response(
            row[1], user_session.user_id
        )

    async def create_debtor(
        self, data: CreateDebtorRequest, user_session: UserSession
    ) -> DebtorModel:
        # El deudor es de una sola empresa: se exige el permiso sobre la organización
        # indicada (el global pasa por `require_permission`). El chequeo de duplicado va
        # acotado a esa organización, así un 409 nunca revela deudores de otra empresa.
        require_permission(PORTFOLIO_CLIENTS, user_session, str(data.organization_id))
        doc_hash = encrypt_service.hash_document(data.document_number)
        existing = await self.debtor_repo.get_by_document_number(
            data.organization_id, doc_hash
        )
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "El deudor ya existe")
        logger.info(
            "[debtor] creando deudor | org=%s doc_type=%s",
            data.organization_id,
            data.document_type,
        )
        return await self.debtor_repo.add(
            DebtorModel(
                organization_id=data.organization_id,
                full_name=data.full_name,
                debtor_type=data.debtor_type,
                document_type=data.document_type,
                document_number=encrypt_service.encrypt_to_str(data.document_number),
                document_number_hash=doc_hash,
            )
        )

    async def create_address(
        self,
        debtor_id: uuid.UUID,
        data: CreateAddressRequest,
        user_session: UserSession,
        portfolio_id: uuid.UUID | None,
    ) -> AddressModel:
        if portfolio_id is not None:
            await self._check_portfolio_access(user_session, portfolio_id)
        elif not user_session.is_global:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "portfolioId es requerido")
        await self._require_debtor(debtor_id, portfolio_id)
        return await self.address_repo.add(
            AddressModel(
                debtor_id=debtor_id,
                address=data.address,
                city=data.city,
                state=data.state,
                country=data.country,
                address_type=data.address_type,
            )
        )

    async def create_contact_method(
        self,
        debtor_id: uuid.UUID,
        data: CreateContactMethodRequest,
        user_session: UserSession,
        portfolio_id: uuid.UUID | None,
    ) -> ContactMethodModel:
        if portfolio_id is not None:
            await self._check_portfolio_access(user_session, portfolio_id)
        elif not user_session.is_global:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "portfolioId es requerido")
        await self._require_debtor(debtor_id, portfolio_id)
        # Normalizar antes de insertar: EMAIL en minúsculas; PHONE con indicativo
        # del país del portafolio del deudor. Mantiene los contactos comparables
        # con el dato autogestionado.
        phone_prefix = await self._resolve_debtor_phone_prefix(debtor_id)
        value = normalize_contact_value(
            data.contact_type, data.contact_value, phone_prefix
        )
        return await self.contact_repo.add(
            ContactMethodModel(
                debtor_id=debtor_id,
                contact_type=data.contact_type,
                contact_value=value,
            )
        )

    async def _resolve_debtor_phone_prefix(self, debtor_id: uuid.UUID) -> str | None:
        """Indicativo telefónico del país del portafolio del deudor (por su
        crédito más reciente)."""
        credits = await self.credit_repo.get_by_debtor_id(debtor_id)
        if not credits:
            return None
        portfolio = await self.portfolio_repo.get_by_id(credits[0].portfolio_id)
        if portfolio is None:
            return None
        return await self._country_repo.get_phone_prefix(portfolio.country)

    async def _check_portfolio_access(
        self, user_session: UserSession, portfolio_id: uuid.UUID
    ) -> None:
        portfolio = await self.portfolio_repo.get_by_id(portfolio_id)
        await check_portfolio_org_access(user_session, portfolio, PORTFOLIO_CLIENTS)

    async def _require_debtor(
        self, debtor_id: uuid.UUID, portfolio_id: uuid.UUID | None = None
    ) -> DebtorModel:
        debtor = await self.debtor_repo.get_by_id(debtor_id)
        if debtor is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Deudor no encontrado")
        if (
            portfolio_id is not None
            and not await self.credit_repo.debtor_belongs_to_portfolio(
                debtor_id, portfolio_id
            )
        ):
            # No se confirma al llamante que el deudor existe fuera de su alcance.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Deudor no encontrado")
        return debtor

    def _to_response(self, debtor: DebtorModel) -> DebtorResponse:
        return DebtorResponse(
            id=debtor.id,
            full_name=debtor.full_name,
            debtor_type=debtor.debtor_type,
            document_type=debtor.document_type,
            document_number=encrypt_service.decrypt_to_str(debtor.document_number),
        )

    def _to_detail(
        self,
        debtor: DebtorModel,
        addresses: list[AddressModel],
        contacts: list[ContactMethodModel],
    ) -> DebtorDetailResponse:
        return DebtorDetailResponse(
            id=debtor.id,
            full_name=debtor.full_name,
            debtor_type=debtor.debtor_type,
            document_type=debtor.document_type,
            document_number=encrypt_service.decrypt_to_str(debtor.document_number),
            addresses=[AddressResponse.model_validate(a) for a in addresses],
            contact_methods=[ContactMethodResponse.model_validate(c) for c in contacts],
        )
