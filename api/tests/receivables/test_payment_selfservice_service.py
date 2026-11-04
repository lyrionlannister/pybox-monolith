"""Regresión IDOR: `PaymentSelfServiceService._resolve_owned_payment` debe responder
404 -- no 403 -- cuando el `payment_id` existe pero pertenece a un crédito de otro
deudor. Mismo criterio que `test_credit_selfservice_service.py`: antes del fix, un
titular autenticado podía distinguir "no existe" de "existe pero no es mío" por el
código de estado, confirmando por fuerza bruta la existencia de pagos de otros
deudores. Se prueba contra el helper privado directamente por la misma razón: es el
único punto de autorización del flujo, sin necesidad de la infraestructura de
tickets/storage que usan `request_reschedule`/`request_validate_payment`."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from core.security.services.encrypt_service import encrypt_service
from identity.users.enums.user_enums import (
    IdentityVerificationStatus,
    UserRole,
    UserScope,
)
from receivables.payments.enums.payment_enums import PaymentStatus
from receivables.payments.models.payment_model import PaymentModel
from receivables.payments.services.payment_selfservice_service import (
    PaymentSelfServiceService,
)
from tests.receivables.conftest import (
    add_organization,
    build_credit,
    build_debtor,
    build_organization,
    build_portfolio,
)


def self_session(make_user_session_factory, document_number_hash: str):
    return make_user_session_factory(
        role=UserRole.USER,
        scope=UserScope.SELF,
        orgs={},
        document_type="CC",
        document_number_hash=document_number_hash,
        identity_verification_status=IdentityVerificationStatus.APPROVED,
    )


async def _add_payment(db_session, credit_id: uuid.UUID, **overrides) -> PaymentModel:
    defaults = dict(
        limit_pay_date=datetime.now(timezone.utc),
        payment_date=datetime.now(timezone.utc),
        payment_amount=100,
        principal_payment=80,
        total_interest_amount=20,
        status=PaymentStatus.PENDING,
        credit_id=credit_id,
    )
    defaults.update(overrides)
    payment = PaymentModel(**defaults)
    db_session.add(payment)
    await db_session.flush()
    return payment


@pytest.fixture
async def payment_of_another_debtor(db_session):
    org = build_organization()
    db_session.add(org)
    await db_session.flush()
    portfolio = build_portfolio(org.id)
    db_session.add(portfolio)
    await db_session.flush()
    owner = build_debtor(org.id)
    db_session.add(owner)
    await db_session.flush()
    credit = build_credit(portfolio.id, owner.id, is_active=True)
    db_session.add(credit)
    await db_session.flush()
    return await _add_payment(db_session, credit.id)


class TestResolveOwnedPaymentIdor:
    async def test_payment_of_another_debtor_raises_404_not_403(
        self, db_session, make_user_session_factory, payment_of_another_debtor
    ):
        requester_doc = "222333444"
        requester = build_debtor(
            (await add_organization(db_session)).id, document_number_plain=requester_doc
        )
        db_session.add(requester)
        await db_session.flush()

        service = PaymentSelfServiceService(db_session)
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document(requester_doc)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service._resolve_owned_payment(session, payment_of_another_debtor.id)
        assert exc_info.value.status_code == 404

    async def test_unknown_payment_raises_404(
        self, db_session, make_user_session_factory
    ):
        requester_doc = "555666777"
        requester = build_debtor(
            (await add_organization(db_session)).id, document_number_plain=requester_doc
        )
        db_session.add(requester)
        await db_session.flush()

        service = PaymentSelfServiceService(db_session)
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document(requester_doc)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service._resolve_owned_payment(session, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_own_payment_resolves(self, db_session, make_user_session_factory):
        doc_number = "888999000"
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        debtor = build_debtor(org.id, document_number_plain=doc_number)
        db_session.add(debtor)
        await db_session.flush()
        portfolio = build_portfolio(org.id, country="CO")
        db_session.add(portfolio)
        await db_session.flush()
        credit = build_credit(portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()
        payment = await _add_payment(db_session, credit.id)

        service = PaymentSelfServiceService(db_session)
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document(doc_number)
        )

        resolved_payment, resolved_credit, org_id, _tz = (
            await service._resolve_owned_payment(session, payment.id)
        )
        assert resolved_payment.id == payment.id
        assert resolved_credit.id == credit.id
        assert org_id == org.id


class TestResolveOwnedPaymentRequiresVerifiedIdentity:
    """Conocer el documento de un deudor no basta: sin identidad aprobada el titular
    no opera sobre sus pagos aunque el documento de la sesión coincida."""

    @pytest.mark.parametrize(
        "status_value",
        [
            IdentityVerificationStatus.NOT_SUBMITTED,
            IdentityVerificationStatus.PENDING,
            IdentityVerificationStatus.DENIED,
        ],
    )
    async def test_own_payment_without_approved_identity_raises_403(
        self, db_session, make_user_session_factory, status_value
    ):
        doc_number = "777000111"
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        debtor = build_debtor(org.id, document_number_plain=doc_number)
        db_session.add(debtor)
        await db_session.flush()
        portfolio = build_portfolio(org.id, country="CO")
        db_session.add(portfolio)
        await db_session.flush()
        credit = build_credit(portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()
        payment = await _add_payment(db_session, credit.id)

        session = make_user_session_factory(
            role=UserRole.USER,
            scope=UserScope.SELF,
            orgs={},
            document_type="CC",
            document_number_hash=encrypt_service.hash_document(doc_number),
            identity_verification_status=status_value,
        )
        with pytest.raises(HTTPException) as exc_info:
            await PaymentSelfServiceService(db_session)._resolve_owned_payment(
                session, payment.id
            )
        assert exc_info.value.status_code == 403
