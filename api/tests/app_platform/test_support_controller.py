import uuid

import pytest
from sqlalchemy import select

from app_platform.support.models.support_ticket_model import SupportTicketModel
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_session_schema import OrgSessionEntry
from tests.factories import get_user_by_email, register_payload

AUTH_BASE = "/api/v1/auth"
ORG_BASE = "/api/v1/organizations"
BASE = "/api/v1/cs/tickets"


def ticket_payload(**overrides) -> dict:
    payload = {
        "title": "No puedo iniciar sesión",
        "topic": "PROBLEMA_ACCESO",
        "notes": "Me sale error al intentar entrar.",
        "priority": "MEDIA",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def real_user_id(client, db_session):
    payload = register_payload()
    resp = await client.post(f"{AUTH_BASE}/register/user", json=payload)
    assert resp.status_code == 201
    user = await get_user_by_email(db_session, payload["email"])
    return user.id


@pytest.fixture
async def authed_global_admin(client, real_user_id, auth_as, make_user_session_factory):
    session = make_user_session_factory(
        user_id=real_user_id, role=UserRole.ADMIN, scope=UserScope.GLOBAL
    )
    return auth_as(session)


@pytest.fixture
async def self_scope_client(client, db_session, auth_as, make_user_session_factory):
    payload = register_payload()
    resp = await client.post(f"{AUTH_BASE}/register/user", json=payload)
    assert resp.status_code == 201
    user = await get_user_by_email(db_session, payload["email"])
    session = make_user_session_factory(
        user_id=user.id, role=UserRole.USER, scope=UserScope.SELF
    )
    return auth_as(session)


@pytest.fixture
async def real_ticket_number(authed_global_admin) -> int:
    resp = await authed_global_admin.post(BASE, json=ticket_payload())
    assert resp.status_code == 201
    return resp.json()["ticketNumber"]


class TestMetrics:
    async def test_valid(self, authed_global_admin):
        resp = await authed_global_admin.get(f"{BASE}/metrics")
        assert resp.status_code == 200
        assert "total" in resp.json()

    async def test_without_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/metrics")
        assert resp.status_code == 401


class TestCategories:
    async def test_valid_staff(self, authed_global_admin):
        resp = await authed_global_admin.get(f"{BASE}/categories")
        assert resp.status_code == 200
        assert any(item["topic"] == "REPORTE_ERROR" for item in resp.json())

    async def test_valid_self_scope(self, self_scope_client):
        resp = await self_scope_client.get(f"{BASE}/categories")
        assert resp.status_code == 200
        assert any(item["topic"] == "REPROGRAMACION_PAGO" for item in resp.json())


class TestTicketOrgs:
    async def test_valid_global(self, authed_global_admin):
        resp = await authed_global_admin.get(f"{BASE}/orgs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestListTickets:
    async def test_valid(self, authed_global_admin):
        resp = await authed_global_admin.get(BASE)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_without_auth_returns_401(self, client):
        resp = await client.get(BASE)
        assert resp.status_code == 401


class TestCreateTicket:
    async def test_valid(self, authed_global_admin):
        resp = await authed_global_admin.post(BASE, json=ticket_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "NUEVO" or body["status"] == "ABIERTO"
        assert body["topic"] == "PROBLEMA_ACCESO"

    async def test_invalid_topic_returns_422(self, authed_global_admin):
        resp = await authed_global_admin.post(
            BASE, json=ticket_payload(topic="no_existe")
        )
        assert resp.status_code == 422

    async def test_payment_topic_returns_400(self, authed_global_admin):
        resp = await authed_global_admin.post(
            BASE, json=ticket_payload(topic="REPROGRAMACION_PAGO")
        )
        assert resp.status_code == 400

    async def test_valid_self_scope_without_org(self, self_scope_client):
        resp = await self_scope_client.post(BASE, json=ticket_payload())
        assert resp.status_code == 201

    async def test_without_auth_returns_401(self, client):
        resp = await client.post(BASE, json=ticket_payload())
        assert resp.status_code == 401


class TestGetTicket:
    async def test_valid(self, authed_global_admin, real_ticket_number):
        resp = await authed_global_admin.get(f"{BASE}/{real_ticket_number}")
        assert resp.status_code == 200
        assert resp.json()["ticketNumber"] == real_ticket_number

    async def test_not_found_returns_404(self, authed_global_admin):
        resp = await authed_global_admin.get(f"{BASE}/999999999")
        assert resp.status_code == 404


class TestUpdateTicketStatus:
    async def test_valid(self, authed_global_admin, real_ticket_number):
        resp = await authed_global_admin.patch(
            f"{BASE}/{real_ticket_number}/status", json={"status": "EN_PROGRESO"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "EN_PROGRESO"

    async def test_terminal_status_returns_400(
        self, authed_global_admin, real_ticket_number
    ):
        resp = await authed_global_admin.patch(
            f"{BASE}/{real_ticket_number}/status", json={"status": "RESUELTO"}
        )
        assert resp.status_code == 400

    async def test_without_permission_returns_403(
        self, authed_global_admin, auth_as, make_user_session_factory
    ):
        create = await authed_global_admin.post(BASE, json=ticket_payload())
        ticket_number = create.json()["ticketNumber"]
        # `auth_as` se aplica al mismo `client` compartido: hay que llamarlo acá, después
        # de crear el ticket como admin, para que la sesión no-staff quede activa recién
        # para esta request (si se pre-autentica en una fixture de setup, el `auth_as`
        # de `authed_global_admin` -- necesario para crear el ticket -- la pisa).
        non_staff = auth_as(
            make_user_session_factory(role=UserRole.USER, scope=UserScope.SELF)
        )
        resp = await non_staff.patch(
            f"{BASE}/{ticket_number}/status", json={"status": "EN_PROGRESO"}
        )
        assert resp.status_code == 403


class TestAssignTicket:
    async def test_valid(self, authed_global_admin, real_ticket_number, real_user_id):
        resp = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/assign", json={"user_id": str(real_user_id)}
        )
        assert resp.status_code == 200
        assert resp.json()["assignedTo"] == str(real_user_id)
        assert resp.json()["status"] == "EN_PROGRESO"

    async def test_without_permission_returns_403(
        self, real_ticket_number, real_user_id, auth_as, make_user_session_factory
    ):
        non_staff = auth_as(
            make_user_session_factory(role=UserRole.USER, scope=UserScope.SELF)
        )
        resp = await non_staff.post(
            f"{BASE}/{real_ticket_number}/assign", json={"user_id": str(real_user_id)}
        )
        assert resp.status_code == 403


class TestUpdateTicketPriority:
    async def test_valid(self, authed_global_admin, real_ticket_number):
        resp = await authed_global_admin.patch(
            f"{BASE}/{real_ticket_number}/priority", json={"priority": "ALTA"}
        )
        assert resp.status_code == 200
        assert resp.json()["priority"] == "ALTA"

    async def test_without_permission_returns_403(
        self, real_ticket_number, auth_as, make_user_session_factory
    ):
        non_staff = auth_as(
            make_user_session_factory(role=UserRole.USER, scope=UserScope.SELF)
        )
        resp = await non_staff.patch(
            f"{BASE}/{real_ticket_number}/priority", json={"priority": "ALTA"}
        )
        assert resp.status_code == 403


class TestEscalateTicket:
    async def test_valid(self, authed_global_admin, real_ticket_number):
        resp = await authed_global_admin.post(f"{BASE}/{real_ticket_number}/escalate")
        assert resp.status_code == 200

    async def test_on_resolved_ticket_returns_409(
        self, authed_global_admin, real_ticket_number
    ):
        await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/resolve",
            json={"approved": True, "notes": "listo"},
        )
        resp = await authed_global_admin.post(f"{BASE}/{real_ticket_number}/escalate")
        assert resp.status_code == 409


class TestResolveTicket:
    async def test_valid(self, authed_global_admin, real_ticket_number):
        resp = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/resolve",
            json={"approved": True, "notes": "Resuelto"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "RESUELTO"

    async def test_already_resolved_returns_409(
        self, authed_global_admin, real_ticket_number
    ):
        await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/resolve",
            json={"approved": True, "notes": "x"},
        )
        resp = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/resolve",
            json={"approved": True, "notes": "x"},
        )
        assert resp.status_code == 409

    async def test_without_permission_returns_403(
        self, real_ticket_number, auth_as, make_user_session_factory
    ):
        non_staff = auth_as(
            make_user_session_factory(role=UserRole.USER, scope=UserScope.SELF)
        )
        resp = await non_staff.post(
            f"{BASE}/{real_ticket_number}/resolve",
            json={"approved": True, "notes": "x"},
        )
        assert resp.status_code == 403


class TestOrgDocs:
    async def test_valid(self, client, db_session, authed_global_admin):
        create_org = await authed_global_admin.post(
            f"{ORG_BASE}/",
            json={"name": f"Org {uuid.uuid4().hex[:8]}", "sector": "FINTECH"},
        )
        org_id = create_org.json()["id"]
        await authed_global_admin.post(f"{ORG_BASE}/{org_id}/request-verification")
        ticket = (
            (
                await db_session.execute(
                    select(SupportTicketModel).where(
                        SupportTicketModel.organization_id == uuid.UUID(org_id)
                    )
                )
            )
            .scalars()
            .first()
        )

        resp = await authed_global_admin.get(f"{BASE}/{ticket.ticket_number}/org-docs")
        assert resp.status_code == 200
        assert len(resp.json()["documents"]) == 3

    async def test_not_a_verification_ticket_returns_400(
        self, authed_global_admin, real_ticket_number
    ):
        resp = await authed_global_admin.get(f"{BASE}/{real_ticket_number}/org-docs")
        assert resp.status_code == 400


async def _org_verification_ticket(authed_global_admin, db_session):
    create_org = await authed_global_admin.post(
        f"{ORG_BASE}/",
        json={"name": f"Org {uuid.uuid4().hex[:8]}", "sector": "FINTECH"},
    )
    org_id = create_org.json()["id"]
    await authed_global_admin.post(f"{ORG_BASE}/{org_id}/request-verification")
    ticket = (
        (
            await db_session.execute(
                select(SupportTicketModel).where(
                    SupportTicketModel.organization_id == uuid.UUID(org_id)
                )
            )
        )
        .scalars()
        .first()
    )
    return org_id, ticket


class TestCrossOrgStaffAccess:
    async def test_org_docs_of_another_org_returns_404(
        self, db_session, authed_global_admin, auth_as, make_user_session_factory
    ):
        _org_id, ticket = await _org_verification_ticket(
            authed_global_admin, db_session
        )
        other_admin = auth_as(
            make_user_session_factory(
                role=None,
                scope=UserScope.ORGANIZATION,
                orgs={
                    str(uuid.uuid4()): OrgSessionEntry(
                        role=UserRole.ADMIN, org_name="Otra"
                    )
                },
            )
        )
        resp = await other_admin.get(f"{BASE}/{ticket.ticket_number}/org-docs")
        assert resp.status_code == 404

    async def test_staff_role_in_one_org_does_not_apply_to_another(
        self, db_session, authed_global_admin, auth_as, make_user_session_factory
    ):
        org_id, ticket = await _org_verification_ticket(authed_global_admin, db_session)
        mixed = auth_as(
            make_user_session_factory(
                role=None,
                scope=UserScope.ORGANIZATION,
                orgs={
                    str(uuid.uuid4()): OrgSessionEntry(
                        role=UserRole.CUSTOMER_SERVICE, org_name="Donde soy CS"
                    ),
                    org_id: OrgSessionEntry(role=UserRole.USER, org_name="Donde no"),
                },
            )
        )
        resolve = await mixed.post(
            f"{BASE}/{ticket.ticket_number}/resolve",
            json={"approved": True, "notes": "x"},
        )
        assert resolve.status_code == 404
        listed = await mixed.get(BASE)
        assert listed.status_code == 200
        assert ticket.ticket_number not in {t["ticketNumber"] for t in listed.json()}


class TestEvents:
    async def test_valid(self, authed_global_admin, real_ticket_number):
        resp = await authed_global_admin.get(f"{BASE}/{real_ticket_number}/events")
        assert resp.status_code == 200
        assert any(e["eventType"] == "CREADO" for e in resp.json())


class TestMessages:
    async def test_create_and_list_valid(self, authed_global_admin, real_ticket_number):
        create = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/messages",
            json={"body": "Hola, ¿alguna novedad?"},
        )
        assert create.status_code == 201
        listing = await authed_global_admin.get(f"{BASE}/{real_ticket_number}/messages")
        assert listing.status_code == 200
        assert len(listing.json()) == 1

    async def test_create_internal_as_staff_valid(
        self, authed_global_admin, real_ticket_number
    ):
        resp = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/messages",
            json={"body": "nota interna", "is_internal": True},
        )
        assert resp.status_code == 201

    async def test_create_internal_as_non_staff_returns_403(self, self_scope_client):
        create = await self_scope_client.post(BASE, json=ticket_payload())
        ticket_number = create.json()["ticketNumber"]
        resp = await self_scope_client.post(
            f"{BASE}/{ticket_number}/messages",
            json={"body": "intento colarme", "is_internal": True},
        )
        assert resp.status_code == 403

    async def test_create_on_resolved_ticket_returns_409(
        self, authed_global_admin, real_ticket_number
    ):
        await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/resolve",
            json={"approved": True, "notes": "x"},
        )
        resp = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/messages", json={"body": "tarde"}
        )
        assert resp.status_code == 409


class TestAttachments:
    async def test_upload_and_list_valid(self, authed_global_admin, real_ticket_number):
        upload = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/attachments",
            files={"files": ("evidencia.png", b"\x89PNG\r\n\x1a\n fake bytes", "image/png")},
        )
        assert upload.status_code == 200
        assert len(upload.json()) == 1

        listing = await authed_global_admin.get(
            f"{BASE}/{real_ticket_number}/attachments"
        )
        assert listing.status_code == 200
        assert len(listing.json()) == 1

    async def test_upload_doc_is_no_longer_allowed(
        self, authed_global_admin, real_ticket_number
    ):
        resp = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/attachments",
            files={"files": ("macro.doc", b"PK", "application/msword")},
        )
        assert resp.status_code == 422

    async def test_upload_content_not_matching_extension_returns_415(
        self, authed_global_admin, real_ticket_number
    ):
        resp = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/attachments",
            files={"files": ("foto.png", b"<html><script>x</script>", "image/png")},
        )
        assert resp.status_code == 415

    async def test_upload_disallowed_extension_returns_422(
        self, authed_global_admin, real_ticket_number
    ):
        resp = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/attachments",
            files={"files": ("script.exe", b"MZ", "application/octet-stream")},
        )
        assert resp.status_code == 422

    async def test_get_content_valid(self, authed_global_admin, real_ticket_number):
        upload = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/attachments",
            files={"files": ("evidencia.png", b"\x89PNG\r\n\x1a\n fake bytes", "image/png")},
        )
        document_id = upload.json()[0]["url"].rsplit("/", 2)[1]
        resp = await authed_global_admin.get(
            f"{BASE}/{real_ticket_number}/documents/{document_id}/content"
        )
        assert resp.status_code == 200
        assert resp.content == b"\x89PNG\r\n\x1a\n fake bytes"

    async def test_closure_attachments_valid(
        self, authed_global_admin, real_ticket_number
    ):
        upload = await authed_global_admin.post(
            f"{BASE}/{real_ticket_number}/closure-attachments",
            files={"files": ("cierre.pdf", b"%PDF-1.4 x", "application/pdf")},
        )
        assert upload.status_code == 200
        listing = await authed_global_admin.get(
            f"{BASE}/{real_ticket_number}/closure-attachments"
        )
        assert listing.status_code == 200
        assert len(listing.json()) == 1

    async def test_closure_attachments_without_permission_returns_403(
        self, self_scope_client
    ):
        create = await self_scope_client.post(BASE, json=ticket_payload())
        ticket_number = create.json()["ticketNumber"]
        resp = await self_scope_client.post(
            f"{BASE}/{ticket_number}/closure-attachments",
            files={"files": ("cierre.pdf", b"%PDF-1.4 x", "application/pdf")},
        )
        assert resp.status_code == 403
