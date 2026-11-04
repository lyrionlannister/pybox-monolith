"""Tests unitarios de `JudicialNotificationService`: emisión desde el panel de la
entidad (permiso por organización dueña del crédito), buzón del titular (resuelto
por documento, cruzando organizaciones) y adjuntos (subida solo por la entidad,
descarga por ambos lados). Contra repos reales atados a `db_session`; los adjuntos se
guardan en el storage real de test (`_object_storage`, ver tests/conftest.py)."""

import io
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from app_platform.documents.enums.document_enums import MAX_DOCUMENT_SIZE_BYTES
from app_platform.notifications.models.notification_model import NotificationModel
from core.security.constants.permissions import PORTFOLIO_JUDICIAL
from core.security.services.encrypt_service import encrypt_service
from identity.organizations.enums.organization_enums import VerificationStatus
from identity.users.enums.user_enums import (
    IdentityVerificationStatus,
    UserRole,
    UserScope,
)
from identity.users.schemas.user_session_schema import OrgSessionEntry, UserSession
from receivables.judicial_notifications.enums.judicial_notification_enums import (
    JudicialPriority,
)
from receivables.judicial_notifications.schemas.judicial_notification_schemas import (
    JudicialNotificationCreate,
)
from receivables.judicial_notifications.services.judicial_notification_service import (
    JudicialNotificationService,
)
from tests.factories import get_user_by_email, register_payload
from tests.receivables.conftest import (
    build_credit,
    build_debtor,
    build_organization,
    build_portfolio,
)

AUTH_BASE = "/api/v1/auth"


def make_upload_file(
    content: bytes, filename: str, content_type: str = "application/pdf"
) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers={"content-type": content_type},
    )


def org_session(
    make_user_session_factory,
    org_id: uuid.UUID,
    *,
    role: UserRole = UserRole.USER,
    **kwargs,
) -> UserSession:
    return make_user_session_factory(
        role=role,
        scope=UserScope.ORGANIZATION,
        orgs={
            str(org_id): OrgSessionEntry(
                role=role,
                org_name="Org",
                verification_status=VerificationStatus.APPROVED,
                permissions=frozenset({PORTFOLIO_JUDICIAL}),
            )
        },
        **kwargs,
    )


def no_access_session(make_user_session_factory) -> UserSession:
    return make_user_session_factory(
        role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
    )


def self_session(make_user_session_factory, document_number_hash: str) -> UserSession:
    return make_user_session_factory(
        role=UserRole.USER,
        scope=UserScope.SELF,
        orgs={},
        document_type="CC",
        document_number_hash=document_number_hash,
        # _require_debtors (ver judicial_notification_service.py) exige identidad
        # verificada además de ser deudor conocido: sin esto, el acceso se corta
        # antes de llegar a la lógica de pertenencia que prueban estos tests.
        identity_verification_status=IdentityVerificationStatus.APPROVED,
    )


@pytest.fixture
async def org_portfolio_credit(db_session):
    org = build_organization()
    db_session.add(org)
    await db_session.flush()
    portfolio = build_portfolio(org.id)
    db_session.add(portfolio)
    await db_session.flush()
    doc_number = "800111222"
    debtor = build_debtor(org.id, document_number_plain=doc_number)
    db_session.add(debtor)
    await db_session.flush()
    credit = build_credit(portfolio.id, debtor.id)
    db_session.add(credit)
    await db_session.flush()
    return org, portfolio, debtor, credit, doc_number


class TestListPriorities:
    async def test_returns_all_priorities_with_labels(self, db_session):
        service = JudicialNotificationService(db_session)
        result = service.list_priorities()
        values = {p.value for p in result}
        assert values == {"URGENTE", "MEDIA", "BAJA", "INFORMATIVA"}
        urgent = next(p for p in result if p.value == "URGENTE")
        assert urgent.label == "Urgente"


class TestCreate:
    async def test_unknown_credit_raises_404(
        self, db_session, make_user_session_factory, real_admin_user_id
    ):
        service = JudicialNotificationService(db_session)
        session = no_access_session(make_user_session_factory)
        payload = JudicialNotificationCreate(
            credit_id=uuid.uuid4(),
            title="T",
            body="B",
            priority=JudicialPriority.URGENT,
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.create(session, payload)
        assert exc_info.value.status_code == 404

    async def test_outside_org_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_credit
    ):
        _, _, _, credit, _ = org_portfolio_credit
        service = JudicialNotificationService(db_session)
        session = no_access_session(make_user_session_factory)
        payload = JudicialNotificationCreate(
            credit_id=credit.id, title="T", body="B", priority=JudicialPriority.URGENT
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.create(session, payload)
        assert exc_info.value.status_code == 404

    async def test_creates_and_notifies_debtor_with_matching_account(
        self,
        db_session,
        client,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, debtor, credit, doc_number = org_portfolio_credit

        # Titular con cuenta real, mismo documento que el deudor -- debe recibir la
        # campana de `_notify_recipients`.
        payload = register_payload(document_number=doc_number, document_type="CC")
        resp = await client.post(f"{AUTH_BASE}/register/user", json=payload)
        assert resp.status_code == 201
        debtor_user = await get_user_by_email(db_session, payload["email"])

        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)

        create_payload = JudicialNotificationCreate(
            credit_id=credit.id,
            title="Embargo",
            body="Detalle",
            priority=JudicialPriority.URGENT,
        )
        result = await service.create(issuer_session, create_payload)

        assert result.credit_id == credit.id
        assert result.credit_number == credit.credit_number
        assert result.entity_name == org.name
        assert result.priority == JudicialPriority.URGENT

        rows = await db_session.execute(
            select(NotificationModel).where(NotificationModel.user_id == debtor_user.id)
        )
        notifications = rows.scalars().all()
        assert len(notifications) == 1
        assert notifications[0].notif_type == "error"  # URGENT -> error
        assert notifications[0].category == "judicial"

    async def test_creates_without_notifying_when_debtor_has_no_account(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)

        create_payload = JudicialNotificationCreate(
            credit_id=credit.id,
            title="Embargo",
            body="Detalle",
            priority=JudicialPriority.LOW,
        )
        result = await service.create(issuer_session, create_payload)

        # No debe reventar por no encontrar usuario a quien notificar -- la notificación
        # judicial se crea igual, solo que sin campana asociada.
        assert result.id is not None

    async def test_custom_notified_at_is_persisted(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        custom_date = datetime(2025, 1, 1, tzinfo=timezone.utc)

        create_payload = JudicialNotificationCreate(
            credit_id=credit.id,
            title="T",
            body="B",
            priority=JudicialPriority.MEDIUM,
            notified_at=custom_date,
        )
        result = await service.create(issuer_session, create_payload)

        assert result.notified_at == custom_date


class TestListByCredit:
    async def test_unknown_credit_raises_404(
        self, db_session, make_user_session_factory
    ):
        service = JudicialNotificationService(db_session)
        session = no_access_session(make_user_session_factory)
        with pytest.raises(HTTPException) as exc_info:
            await service.list_by_credit(session, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_outside_org_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_credit
    ):
        _, _, _, credit, _ = org_portfolio_credit
        service = JudicialNotificationService(db_session)
        session = no_access_session(make_user_session_factory)
        with pytest.raises(HTTPException) as exc_info:
            await service.list_by_credit(session, credit.id)
        assert exc_info.value.status_code == 404

    async def test_lists_notifications_for_credit(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id,
                title="T1",
                body="B1",
                priority=JudicialPriority.LOW,
            ),
        )
        await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id,
                title="T2",
                body="B2",
                priority=JudicialPriority.MEDIUM,
            ),
        )

        result = await service.list_by_credit(issuer_session, credit.id)
        assert len(result) == 2
        assert result[0].notified_at >= result[1].notified_at


class TestUploadAttachments:
    async def test_unknown_notification_raises_404(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, _, _ = org_portfolio_credit
        service = JudicialNotificationService(db_session)
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_attachments(
                issuer_session, uuid.uuid4(), [make_upload_file(b"x", "orden.pdf")]
            )
        assert exc_info.value.status_code == 404

    async def test_outside_org_raises_404(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id, title="T", body="B", priority=JudicialPriority.LOW
            ),
        )
        no_access = no_access_session(make_user_session_factory)
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_attachments(
                no_access, created.id, [make_upload_file(b"x", "orden.pdf")]
            )
        assert exc_info.value.status_code == 404

    async def test_disallowed_extension_raises_415(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id, title="T", body="B", priority=JudicialPriority.LOW
            ),
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_attachments(
                issuer_session, created.id, [make_upload_file(b"x", "malware.exe")]
            )
        assert exc_info.value.status_code == 415

    async def test_exceeds_size_limit_raises_413(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id, title="T", body="B", priority=JudicialPriority.LOW
            ),
        )
        oversized = b"0" * (MAX_DOCUMENT_SIZE_BYTES + 1)
        with pytest.raises(HTTPException) as exc_info:
            await service.upload_attachments(
                issuer_session, created.id, [make_upload_file(oversized, "orden.pdf")]
            )
        assert exc_info.value.status_code == 413

    async def test_uploads_and_attachments_travel_in_responses(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, doc_number = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id, title="T", body="B", priority=JudicialPriority.LOW
            ),
        )
        content = b"%PDF-1.4 fake content"

        result = await service.upload_attachments(
            issuer_session, created.id, [make_upload_file(content, "orden.pdf")]
        )
        assert len(result.attachments) == 1
        assert result.attachments[0].name == "orden.pdf"
        assert result.attachments[0].size == len(content)

        # Sin N+1: list_by_credit debe traer el mismo adjunto resolviendo documentos en
        # una sola consulta batch, no una por notificación.
        listed = await service.list_by_credit(issuer_session, credit.id)
        assert len(listed) == 1
        assert len(listed[0].attachments) == 1

        doc_hash = encrypt_service.hash_document(doc_number)
        self_sess = self_session(make_user_session_factory, doc_hash)
        inbox = await service.get_my_inbox(self_sess)
        assert len(inbox.items[0].attachments) == 1


class TestGetAttachmentContent:
    async def test_entity_with_permission_downloads(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id, title="T", body="B", priority=JudicialPriority.LOW
            ),
        )
        uploaded = await service.upload_attachments(
            issuer_session,
            created.id,
            [make_upload_file(b"%PDF-1.4 content", "orden.pdf")],
        )
        document_id = uploaded.attachments[0].id

        response = await service.get_attachment_content(
            issuer_session, created.id, document_id
        )
        assert response.status_code == 200

    async def test_entity_outside_org_raises_404(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id, title="T", body="B", priority=JudicialPriority.LOW
            ),
        )
        uploaded = await service.upload_attachments(
            issuer_session,
            created.id,
            [make_upload_file(b"%PDF-1.4 content", "orden.pdf")],
        )
        document_id = uploaded.attachments[0].id

        no_access = no_access_session(make_user_session_factory)
        with pytest.raises(HTTPException) as exc_info:
            await service.get_attachment_content(no_access, created.id, document_id)
        assert exc_info.value.status_code == 404

    async def test_debtor_owner_downloads(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, doc_number = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id, title="T", body="B", priority=JudicialPriority.LOW
            ),
        )
        uploaded = await service.upload_attachments(
            issuer_session,
            created.id,
            [make_upload_file(b"%PDF-1.4 content", "orden.pdf")],
        )
        document_id = uploaded.attachments[0].id

        doc_hash = encrypt_service.hash_document(doc_number)
        self_sess = self_session(make_user_session_factory, doc_hash)
        response = await service.get_attachment_content(
            self_sess, created.id, document_id
        )
        assert response.status_code == 200

    async def test_debtor_of_other_credit_raises_404(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, portfolio, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id, title="T", body="B", priority=JudicialPriority.LOW
            ),
        )
        uploaded = await service.upload_attachments(
            issuer_session,
            created.id,
            [make_upload_file(b"%PDF-1.4 content", "orden.pdf")],
        )
        document_id = uploaded.attachments[0].id

        other_doc = "999888777"
        other_debtor = build_debtor(org.id, document_number_plain=other_doc)
        db_session.add(other_debtor)
        await db_session.flush()

        other_hash = encrypt_service.hash_document(other_doc)
        other_session = self_session(make_user_session_factory, other_hash)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_attachment_content(other_session, created.id, document_id)
        assert exc_info.value.status_code == 404


class TestSelfServiceInbox:
    async def test_get_my_inbox_without_matching_debtor_raises_404(
        self, db_session, make_user_session_factory
    ):
        service = JudicialNotificationService(db_session)
        session = self_session(
            make_user_session_factory, encrypt_service.hash_document("000000000")
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.get_my_inbox(session)
        assert exc_info.value.status_code == 404

    async def test_get_my_inbox_lists_own_and_counts_unread(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, debtor, credit, doc_number = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id,
                title="T1",
                body="B1",
                priority=JudicialPriority.LOW,
            ),
        )

        doc_hash = encrypt_service.hash_document(doc_number)
        self_sess = self_session(make_user_session_factory, doc_hash)

        inbox = await service.get_my_inbox(self_sess)
        assert len(inbox.items) == 1
        assert inbox.unread_count == 1

    async def test_mark_read_updates_notification(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, doc_number = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id,
                title="T1",
                body="B1",
                priority=JudicialPriority.LOW,
            ),
        )

        doc_hash = encrypt_service.hash_document(doc_number)
        self_sess = self_session(make_user_session_factory, doc_hash)

        await service.mark_read(self_sess, created.id)

        inbox = await service.get_my_inbox(self_sess)
        assert inbox.unread_count == 0
        assert inbox.items[0].is_read is True

    async def test_mark_read_unknown_notification_raises_404(
        self, db_session, make_user_session_factory, org_portfolio_credit
    ):
        _, _, _, _, doc_number = org_portfolio_credit
        service = JudicialNotificationService(db_session)
        doc_hash = encrypt_service.hash_document(doc_number)
        self_sess = self_session(make_user_session_factory, doc_hash)

        with pytest.raises(HTTPException) as exc_info:
            await service.mark_read(self_sess, uuid.uuid4())
        assert exc_info.value.status_code == 404

    async def test_mark_read_other_debtors_notification_raises_404(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, portfolio, _, credit, _ = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        created = await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id,
                title="T1",
                body="B1",
                priority=JudicialPriority.LOW,
            ),
        )

        other_doc = "999888777"
        other_debtor = build_debtor(org.id, document_number_plain=other_doc)
        db_session.add(other_debtor)
        await db_session.flush()
        other_credit = build_credit(portfolio.id, other_debtor.id)
        db_session.add(other_credit)
        await db_session.flush()

        other_hash = encrypt_service.hash_document(other_doc)
        other_session = self_session(make_user_session_factory, other_hash)

        with pytest.raises(HTTPException) as exc_info:
            await service.mark_read(other_session, created.id)
        assert exc_info.value.status_code == 404

    async def test_mark_all_read(
        self,
        db_session,
        make_user_session_factory,
        org_portfolio_credit,
        real_admin_user_id,
    ):
        org, _, _, credit, doc_number = org_portfolio_credit
        issuer_session = org_session(
            make_user_session_factory,
            org.id,
            role=UserRole.ADMIN,
            user_id=real_admin_user_id,
        )
        service = JudicialNotificationService(db_session)
        await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id,
                title="T1",
                body="B1",
                priority=JudicialPriority.LOW,
            ),
        )
        await service.create(
            issuer_session,
            JudicialNotificationCreate(
                credit_id=credit.id,
                title="T2",
                body="B2",
                priority=JudicialPriority.MEDIUM,
            ),
        )

        doc_hash = encrypt_service.hash_document(doc_number)
        self_sess = self_session(make_user_session_factory, doc_hash)

        await service.mark_all_read(self_sess)

        inbox = await service.get_my_inbox(self_sess)
        assert inbox.unread_count == 0
