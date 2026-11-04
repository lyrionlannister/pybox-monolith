"""Regresión IDOR: `CreditSelfServiceService._resolve_owned_credit` debe responder
404 -- no 403 -- cuando el `credit_id` existe pero pertenece a otro deudor. Antes
del fix, un titular autenticado podía distinguir por el código de estado "ese id no
existe" (404) de "ese id existe pero no es tuyo" (403), permitiendo confirmar por
fuerza bruta de UUIDs qué créditos de OTROS deudores existen en el sistema. Se
prueba contra el helper privado directamente (no contra `request_settlement`
completo): es el único punto de autorización de ese flujo, y ejercitarlo a través
del ticket de soporte agregaría infraestructura de storage/tickets irrelevante
para esta verificación."""

import uuid

import pytest
from fastapi import HTTPException

from core.security.services.encrypt_service import encrypt_service
from identity.users.enums.user_enums import (
    IdentityVerificationStatus,
    UserRole,
    UserScope,
)
from receivables.credits.services.credit_selfservice_service import (
    CreditSelfServiceService,
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


@pytest.fixture
async def credit_of_another_debtor(db_session):
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
    return credit


class TestResolveOwnedCreditIdor:
    async def test_credit_of_another_debtor_raises_404_not_403(
        self, db_session, make_user_session_factory, credit_of_another_debtor
    ):
        requester_doc = "111222333"
        requester = build_debtor(
            (await add_organization(db_session)).id, document_number_plain=requester_doc
        )
        db_session.add(requester)
        await db_session.flush()

        service = CreditSelfServiceService(db_session)
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document(requester_doc)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service._resolve_owned_credit(session, credit_of_another_debtor.id)
        assert exc_info.value.status_code == 404

    async def test_unknown_credit_raises_404(
        self, db_session, make_user_session_factory
    ):
        requester_doc = "444555666"
        requester = build_debtor(
            (await add_organization(db_session)).id, document_number_plain=requester_doc
        )
        db_session.add(requester)
        await db_session.flush()

        service = CreditSelfServiceService(db_session)
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document(requester_doc)
        )

        with pytest.raises(HTTPException) as exc_info:
            await service._resolve_owned_credit(session, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_own_credit_resolves(self, db_session, make_user_session_factory):
        doc_number = "777888999"
        org = build_organization()
        db_session.add(org)
        await db_session.flush()
        debtor = build_debtor(org.id, document_number_plain=doc_number)
        db_session.add(debtor)
        await db_session.flush()
        portfolio = build_portfolio(org.id)
        db_session.add(portfolio)
        await db_session.flush()
        credit = build_credit(portfolio.id, debtor.id, is_active=True)
        db_session.add(credit)
        await db_session.flush()

        service = CreditSelfServiceService(db_session)
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document(doc_number)
        )

        resolved_credit, org_id = await service._resolve_owned_credit(
            session, credit.id
        )
        assert resolved_credit.id == credit.id
        assert org_id == org.id
