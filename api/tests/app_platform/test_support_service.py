"""Resolución de la verificación de identidad de un titular desde soporte."""

from sqlalchemy import select

from app_platform.support.services.support_service import SupportService
from identity.users.enums.user_enums import IdentityVerificationStatus
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType
from receivables.contact_methods.models.contact_method_model import ContactMethodModel
from tests.factories import get_user_by_email, register_payload
from tests.receivables.conftest import add_organization, build_debtor

AUTH_BASE = "/api/v1/auth"


async def _registered_user(client, db_session, status_value):
    payload = register_payload()
    resp = await client.post(f"{AUTH_BASE}/register/user", json=payload)
    assert resp.status_code == 201
    user = await get_user_by_email(db_session, payload["email"])
    user.identity_verification_status = status_value
    user.is_email_verified = True
    await db_session.flush()
    return user, payload


async def _email_contacts(db_session, debtor_id):
    result = await db_session.execute(
        select(ContactMethodModel).where(
            ContactMethodModel.debtor_id == debtor_id,
            ContactMethodModel.contact_type == ContactMethodType.EMAIL,
        )
    )
    return result.scalars().all()


class TestResolveIdentityVerification:
    async def test_approval_propagates_verified_contacts(self, client, db_session):
        user, payload = await _registered_user(
            client, db_session, IdentityVerificationStatus.PENDING
        )
        org = await add_organization(db_session)
        debtor = build_debtor(org.id, document_number_plain=payload["document_number"])
        db_session.add(debtor)
        await db_session.flush()

        await SupportService(db_session)._resolve_identity_verification(
            user.id, approved=True
        )

        await db_session.refresh(user)
        assert user.identity_verification_status == IdentityVerificationStatus.APPROVED
        assert len(await _email_contacts(db_session, debtor.id)) == 1

    async def test_rejection_does_not_propagate_contacts(self, client, db_session):
        user, payload = await _registered_user(
            client, db_session, IdentityVerificationStatus.PENDING
        )
        org = await add_organization(db_session)
        debtor = build_debtor(org.id, document_number_plain=payload["document_number"])
        db_session.add(debtor)
        await db_session.flush()

        await SupportService(db_session)._resolve_identity_verification(
            user.id, approved=False
        )

        await db_session.refresh(user)
        assert user.identity_verification_status == IdentityVerificationStatus.DENIED
        assert await _email_contacts(db_session, debtor.id) == []

    async def test_stale_ticket_does_not_approve_reset_identity(
        self, client, db_session
    ):
        user, _payload = await _registered_user(
            client, db_session, IdentityVerificationStatus.NOT_SUBMITTED
        )

        await SupportService(db_session)._resolve_identity_verification(
            user.id, approved=True
        )

        await db_session.refresh(user)
        assert (
            user.identity_verification_status
            == IdentityVerificationStatus.NOT_SUBMITTED
        )
