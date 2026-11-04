"""Resuelve el crédito/pago de un titular verificando que le pertenezca (SELF)."""

import uuid

from fastapi import HTTPException, status

from app_platform.countries.enums.country_enums import UserDocumentType
from core.security.policies.security_policies import (
    get_self_identity,
    require_verified_identity,
)
from identity.users.schemas.user_session_schema import UserSession
from receivables.credits.models.credit_model import CreditModel
from receivables.credits.repository.credit_repository import CreditRepository
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.payments.enums.payment_enums import PaymentStatus
from receivables.payments.models.payment_model import PaymentModel
from receivables.payments.repository.payment_repository import PaymentRepository
from receivables.portfolios.models.portfolio_model import PortfolioModel
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository


class PaymentOwnershipResolver:
    """Cadena de pertenencia de una cuota para el titular (scope SELF): documento ->
    deudores -> pago -> crédito -> portafolio. Extraído de
    `PaymentSelfServiceService._resolve_owned_payment` para que el checkout de Wompi
    (`payment_checkout_service.py`) valide la MISMA cadena sin duplicarla — un bug de
    autorización arreglado en un lado y no en el otro es exactamente el riesgo que esto
    evita (ver skill `tenant-isolation`, Paso 1.2)."""

    def __init__(
        self,
        debtor_repo: DebtorRepository,
        credit_repo: CreditRepository,
        payment_repo: PaymentRepository,
        portfolio_repo: PortfolioRepository,
    ) -> None:
        self._debtor_repo = debtor_repo
        self._credit_repo = credit_repo
        self._payment_repo = payment_repo
        self._portfolio_repo = portfolio_repo

    async def resolve_owned_payment(
        self,
        session: UserSession,
        payment_id: uuid.UUID,
        *,
        require_pending: bool = True,
    ) -> tuple[PaymentModel, CreditModel, PortfolioModel]:
        require_verified_identity(session)
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

        payment = await self._payment_repo.get_by_id(payment_id)
        if payment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Pago no encontrado.")

        credit = await self._credit_repo.get_by_id(payment.credit_id)
        # 404 genérico también cuando el pago existe pero el crédito no es del titular:
        # un 403 distinto de "no encontrado" deja adivinar por fuerza bruta qué IDs de
        # pago existen en el sistema, aunque sean de otro deudor.
        if credit is None or not ({credit.debtor_id, credit.codebtor_id} & debtor_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Pago no encontrado.")

        if require_pending and payment.status != PaymentStatus.PENDING:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Este pago ya tiene una solicitud en curso o no admite solicitudes.",
            )

        portfolio = await self._portfolio_repo.get_by_id(credit.portfolio_id)
        if portfolio is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Portafolio no encontrado.")

        return payment, credit, portfolio
