"""Autogestión de créditos del titular: solicitud de liquidación (settlement)."""

import uuid
from decimal import Decimal

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import UserDocumentType
from app_platform.support.enums.support_enums import PaymentTopic
from app_platform.support.schemas.support_schemas import SupportFilter
from app_platform.support.services.support_service import SupportService
from core.security.policies.security_policies import get_self_identity
from identity.users.schemas.user_session_schema import UserSession
from receivables.credits.models.credit_settlement_ticket_model import (
    CreditSettlementTicketModel,
)
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.credits.repository.credit_settlement_ticket_repository import (
    CreditSettlementTicketRepository,
)
from receivables.credits.schemas.credit_selfservice_schemas import (
    SettlementRequestResponse,
)
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository


class CreditSelfServiceService:
    """Autogestión del titular (rol USER, scope SELF): dar de baja (saldar) un crédito
    propio adjuntando un comprobante. Crea un ticket asignado al CUSTOMER_SERVICE de la
    organización dueña; al aprobarlo se registra el pago total y se desactiva el crédito
    (ver CreditSettlementResolutionService)."""

    def __init__(self, session: AsyncSession) -> None:
        self._debtor_repo = DebtorRepository(session)
        self._credit_repo = CreditRepository(session)
        self._portfolio_repo = PortfolioRepository(session)
        self._settlement_ticket_repo = CreditSettlementTicketRepository(session)
        self._support = SupportService(session)

    async def request_settlement(
        self, session: UserSession, credit_id: uuid.UUID, files: list[UploadFile]
    ) -> SettlementRequestResponse:
        if not files:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Adjunta al menos un comprobante."
            )

        credit, org_id = await self._resolve_owned_credit(session, credit_id)

        if not credit.is_active:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Este crédito ya fue dado de baja."
            )
        if (
            await self._settlement_ticket_repo.get_active_by_credit_id(credit.id)
            is not None
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ya hay una solicitud de baja en curso para este crédito.",
            )

        total = self._settlement_amount(credit)

        ticket = await self._support.create_payment_ticket(
            org_id=org_id,
            created_by=session.user_id,
            topic=PaymentTopic.CREDIT_SETTLEMENT,
            title=f"Baja de crédito · {credit.credit_number}",
            notes=(
                f"El titular solicita dar de baja el crédito {credit.credit_number} "
                f"por un monto total de {total:.2f} y adjunta comprobante."
            ),
        )

        # El comprobante queda en el almacén de objetos como adjunto del ticket,
        # reutilizando la validación de extensión/tamaño existente.
        upload_filter = SupportFilter(created_by=session.user_id, can_create=True)
        await self._support.upload_attachments(
            ticket.ticket_number, files, upload_filter
        )

        await self._settlement_ticket_repo.add(
            CreditSettlementTicketModel(
                ticket_id=ticket.id,
                credit_id=credit.id,
                settlement_amount=total,
            )
        )

        return SettlementRequestResponse(
            ticket_number=ticket.ticket_number, settlement_amount=total
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_owned_credit(
        self, session: UserSession, credit_id: uuid.UUID
    ) -> tuple[object, uuid.UUID]:
        doc_type_str, doc_number_hash = get_self_identity(session)
        try:
            doc_type = UserDocumentType(doc_type_str)
        except ValueError as e:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Documento de identidad inválido."
            ) from e

        # Una fila de deudor por empresa: el crédito es del titular si lo es en
        # cualquiera.
        debtors = await self._debtor_repo.list_by_document(doc_type, doc_number_hash)
        if not debtors:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "No se encontró tu registro de deudor."
            )
        debtor_ids = {d.id for d in debtors}

        credit = await self._credit_repo.get_by_id(credit_id)
        # 404 genérico también cuando el crédito existe pero no es del titular: un
        # 403 distinto de "no encontrado" deja adivinar por fuerza bruta qué IDs de
        # crédito existen en el sistema, aunque sean de otro deudor.
        if credit is None or not ({credit.debtor_id, credit.codebtor_id} & debtor_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Crédito no encontrado.")

        portfolio = await self._portfolio_repo.get_by_id(credit.portfolio_id)
        if portfolio is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Portafolio no encontrado.")

        return credit, portfolio.organization_id

    @staticmethod
    def _settlement_amount(credit) -> Decimal:
        """Monto total a saldar: saldo en mora + intereses corrientes + intereses de
        mora + otros conceptos."""
        return (
            credit.overdue_principal_balance
            + credit.current_interest
            + credit.overdue_interest
            + credit.other_concepts
        )
