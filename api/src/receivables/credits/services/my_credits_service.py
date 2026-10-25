"""Consulta de autogestión: créditos y pagos del deudor autenticado."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import UserDocumentType
from app_platform.countries.repository.country_repository import CountryRepository
from core.security.services.encrypt_service import encrypt_service
from identity.organizations.repository.organization_repository import (
    OrganizationRepository,
)
from identity.users.enums.user_enums import IdentityVerificationStatus
from receivables.credits.models.credit_model import CreditModel
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.credits.repository.credit_settlement_ticket_repository import (
    CreditSettlementTicketRepository,
)
from receivables.credits.schemas.my_credits_schemas import (
    CreditWithPayments,
    PaymentMethodSummary,
    PaymentSummary,
)
from receivables.debtors.enums.debtor_enums import DebtorType
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payment_methods.repository.payment_method_repository import (
    PaymentMethodRepository,
)
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository


class MyCreditsService:
    def __init__(self, session: AsyncSession) -> None:
        self._debtor_repo = DebtorRepository(session)
        self._credit_repo = CreditRepository(session)
        self._settlement_ticket_repo = CreditSettlementTicketRepository(session)
        self._payment_repo = PaymentRepository(session)
        self._payment_method_repo = PaymentMethodRepository(session)
        self._portfolio_repo = PortfolioRepository(session)
        self._org_repo = OrganizationRepository(session)
        self._country_repo = CountryRepository(session)

    async def get_my_credits(
        self,
        document_type: str,
        document_number_hash: str,
        identity_verification_status: IdentityVerificationStatus,
    ) -> list[CreditWithPayments]:
        try:
            doc_type = UserDocumentType(document_type)
        except ValueError:
            return []

        # Una fila de deudor por empresa: el titular ve sus créditos de todas.
        debtors = await self._debtor_repo.list_by_document(
            doc_type, document_number_hash
        )
        if not debtors:
            return []
        # Ver StatementService._require_self_debtors: conocer tipo+número de documento
        # de alguien no es secreto, así que además de ser deudor conocido se exige
        # identidad verificada (documento subido + aprobado por Atención al Cliente).
        if identity_verification_status != IdentityVerificationStatus.APPROVED:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Verificación de identidad pendiente. Sube tu documento de "
                "identidad para acceder a tu información crediticia.",
            )

        debtor_ids = [d.id for d in debtors]
        all_credits: list[tuple[CreditModel, DebtorType]] = [
            (c, DebtorType.DEBTOR)
            for c in await self._credit_repo.get_by_debtor_ids(debtor_ids)
        ] + [
            (c, DebtorType.CO_DEBTOR)
            for c in await self._credit_repo.get_by_codebtor_ids(debtor_ids)
        ]

        if not all_credits:
            return []

        portfolio_ids: list[uuid.UUID] = list({c.portfolio_id for c, _ in all_credits})
        portfolios = await self._portfolio_repo.get_by_ids(portfolio_ids)
        portfolio_map = {p.id: p for p in portfolios}
        # Un portafolio dado de baja no aparece en `get_by_ids`: sus créditos ya no se
        # muestran al titular (antes esto reventaba con KeyError más abajo).
        all_credits = [
            (c, role) for c, role in all_credits if c.portfolio_id in portfolio_map
        ]
        if not all_credits:
            return []

        org_ids: list[uuid.UUID] = list(
            {p.organization_id for p in portfolio_map.values()}
        )
        orgs = await self._org_repo.get_by_ids(org_ids)
        org_map = {o.id: o.name for o in orgs}

        payment_methods_map: dict[uuid.UUID, list[PaymentMethodSummary]] = {
            org_id: [] for org_id in org_ids
        }
        for m in await self._payment_method_repo.get_active_by_organization_ids(
            org_ids
        ):
            payment_methods_map[m.organization_id].append(
                PaymentMethodSummary(
                    id=m.id,
                    name=m.name,
                    type=m.type.value,
                    description=m.description,
                    instructions=m.instructions,
                    bank_name=m.bank_name,
                    account_type=m.account_type,
                    account_number=(
                        encrypt_service.decrypt_to_str(m.account_number)
                        if m.account_number
                        else None
                    ),
                    payment_link=m.payment_link,
                    qr_image_url=m.qr_image_url,
                )
            )

        country_map = await self._country_repo.get_active_map()

        credit_ids = [credit.id for credit, _ in all_credits]
        payments_by_credit: dict[uuid.UUID, list] = {}
        for p in await self._payment_repo.get_by_credit_ids(credit_ids):
            payments_by_credit.setdefault(p.credit_id, []).append(p)
        active_settlement_credit_ids = (
            await self._settlement_ticket_repo.get_active_credit_ids(credit_ids)
        )

        results: list[CreditWithPayments] = []
        for credit, role in all_credits:
            raw_payments = payments_by_credit.get(credit.id, [])
            payments = [
                PaymentSummary(
                    id=p.id,
                    limit_pay_date=p.limit_pay_date,
                    payment_date=p.payment_date,
                    payment_amount=float(p.payment_amount),
                    installment_number=p.installment_number,
                    principal_payment=float(p.principal_payment),
                    total_interest_amount=float(p.total_interest_amount),
                    other_charges=float(p.other_charges),
                    status=p.status.value,
                )
                for p in raw_payments
            ]

            portfolio = portfolio_map[credit.portfolio_id]
            org_id = portfolio.organization_id
            org_name = org_map.get(org_id, "")
            country = country_map.get(portfolio.country) if portfolio.country else None
            currency_code = country.currency_code if country else "COP"

            settlement_requested = credit.id in active_settlement_credit_ids

            results.append(
                CreditWithPayments(
                    id=credit.id,
                    credit_number=credit.credit_number,
                    credit_type=credit.credit_type,
                    disbursed_date=credit.disbursed_date,
                    total_credit_balance=float(credit.total_credit_balance),
                    overdue_principal_balance=float(credit.overdue_principal_balance),
                    days_overdue_at_cutoff=credit.days_overdue_at_cutoff,
                    role=role,
                    organization_name=org_name or "",
                    currency_code=currency_code,
                    payments=payments,
                    payment_methods=payment_methods_map.get(org_id, []),
                    is_active=credit.is_active,
                    settlement_requested=settlement_requested,
                )
            )

        return results
