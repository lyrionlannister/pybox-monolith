import uuid

import pytest

from identity.organizations.enums.organization_enums import VerificationStatus
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_session_schema import OrgSessionEntry
from tests.factories import get_user_by_email, register_payload

BASE = "/api/v1/organizations"
AUTH_BASE = "/api/v1/auth"


def org_payload(**overrides) -> dict:
    payload = {
        "name": f"Org {uuid.uuid4().hex[:8]}",
        "sector": "FINTECH",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def authed_global_admin(client, db_session, auth_as, make_user_session_factory):
    """Admin global respaldado por un usuario real en DB: varios endpoints de
    organizations refrescan la sesión (`user_service.get_user_session`), que
    falla si el `user_id` de la sesión falsa no existe de verdad."""
    payload = register_payload()
    resp = await client.post(f"{AUTH_BASE}/register/user", json=payload)
    assert resp.status_code == 201
    user = await get_user_by_email(db_session, payload["email"])
    session = make_user_session_factory(
        user_id=user.id, role=UserRole.ADMIN, scope=UserScope.GLOBAL
    )
    return auth_as(session)


def org_scoped_admin_session(make_user_session_factory, org_id: str | None = None):
    """Admin de UNA organización que no existe en la DB real -- sirve para probar
    que `AdminScopeDep` pasa (hay rol ADMIN en algún org) pero el servicio igual
    rechaza operar sobre una organización de la que no es admin de verdad. No se
    respalda con un usuario real porque el flujo corta con 403 antes de llegar
    a ningún código que necesite resolver la sesión contra la DB."""
    return make_user_session_factory(
        role=UserRole.ADMIN,
        scope=UserScope.ORGANIZATION,
        orgs={
            org_id
            or str(uuid.uuid4()): OrgSessionEntry(
                role=UserRole.ADMIN,
                org_name="Otra org",
                verification_status=VerificationStatus.APPROVED,
            )
        },
    )


def no_admin_role_session(make_user_session_factory):
    return make_user_session_factory(
        role=UserRole.USER,
        scope=UserScope.ORGANIZATION,
        orgs={
            str(uuid.uuid4()): OrgSessionEntry(
                role=UserRole.USER,
                org_name="Otra org",
                verification_status=VerificationStatus.APPROVED,
            )
        },
    )


class TestListOrganizations:
    async def test_list_valid_as_global_admin(self, authed_global_admin):
        resp = await authed_global_admin.get(f"{BASE}/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_without_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/")
        assert resp.status_code == 401


class TestListSectors:
    async def test_list_sectors_valid(self, authed_global_admin):
        resp = await authed_global_admin.get(f"{BASE}/sectors")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 8
        assert any(item["value"] == "FINTECH" for item in body)


class TestCreateOrganization:
    async def test_create_valid_as_global_admin(self, authed_global_admin):
        resp = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body["sector"] == "FINTECH"

    async def test_create_missing_sector_returns_422(self, authed_global_admin):
        payload = org_payload()
        del payload["sector"]
        resp = await authed_global_admin.post(f"{BASE}/", json=payload)
        assert resp.status_code == 422

    async def test_create_without_admin_role_returns_403(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(no_admin_role_session(make_user_session_factory))
        resp = await authed.post(f"{BASE}/", json=org_payload())
        assert resp.status_code == 403


class TestGetOrganization:
    async def test_get_valid_as_global_admin(self, authed_global_admin):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]
        resp = await authed_global_admin.get(f"{BASE}/{org_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == org_id

    async def test_get_not_found_returns_404(self, authed_global_admin):
        resp = await authed_global_admin.get(f"{BASE}/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_get_forbidden_for_unrelated_org_scope(
        self, client, authed_global_admin, auth_as, make_user_session_factory
    ):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]

        unrelated = auth_as(org_scoped_admin_session(make_user_session_factory))
        resp = await unrelated.get(f"{BASE}/{org_id}")
        assert resp.status_code == 403


class TestFiscalDocumentNumberDecryption:
    """Regresión para la Fase 3b de la auditoría: el descifrado de
    `fiscal_document_number` se movió del schema (`field_validator`) al service
    (`OrganizationService.to_response`/`to_register_response`), llamado explícitamente
    desde el controller. Si algún endpoint deja de pasar por ahí, este campo vuelve
    silenciosamente el texto cifrado -- por eso se verifica el valor exacto, no solo
    que la respuesta no lance una excepción."""

    async def test_create_and_get_return_plaintext_fiscal_document_number(
        self, authed_global_admin
    ):
        create = await authed_global_admin.post(
            f"{BASE}/", json=org_payload(fiscal_document_number="900123456-7")
        )
        assert create.status_code == 201
        assert create.json()["fiscalDocumentNumber"] == "900123456-7"

        org_id = create.json()["id"]
        get_resp = await authed_global_admin.get(f"{BASE}/{org_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["fiscalDocumentNumber"] == "900123456-7"

    async def test_update_returns_plaintext_fiscal_document_number(
        self, authed_global_admin
    ):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]

        resp = await authed_global_admin.patch(
            f"{BASE}/{org_id}", json={"fiscal_document_number": "800987654-3"}
        )
        assert resp.status_code == 200
        assert resp.json()["fiscalDocumentNumber"] == "800987654-3"


class TestUpdateOrganization:
    async def test_update_valid_as_global_admin(self, authed_global_admin):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]
        resp = await authed_global_admin.patch(
            f"{BASE}/{org_id}", json={"name": "Nombre actualizado"}
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Nombre actualizado"

    async def test_update_not_found_returns_404(self, authed_global_admin):
        resp = await authed_global_admin.patch(
            f"{BASE}/{uuid.uuid4()}", json={"name": "x"}
        )
        assert resp.status_code == 404

    async def test_update_forbidden_for_non_admin_of_org(
        self, authed_global_admin, auth_as, make_user_session_factory
    ):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]

        unrelated = auth_as(org_scoped_admin_session(make_user_session_factory))
        resp = await unrelated.patch(f"{BASE}/{org_id}", json={"name": "hack"})
        assert resp.status_code == 403


class TestRequestVerification:
    async def test_request_verification_valid(self, authed_global_admin):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]
        resp = await authed_global_admin.post(f"{BASE}/{org_id}/request-verification")
        assert resp.status_code == 200

    async def test_request_verification_not_admin_of_org_returns_403(
        self, authed_global_admin, auth_as, make_user_session_factory
    ):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]

        unrelated = auth_as(org_scoped_admin_session(make_user_session_factory))
        resp = await unrelated.post(f"{BASE}/{org_id}/request-verification")
        assert resp.status_code == 403


class TestDeleteOrganization:
    async def test_delete_valid_as_global_admin(self, authed_global_admin):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]
        resp = await authed_global_admin.delete(f"{BASE}/{org_id}")
        assert resp.status_code == 204
        follow_up = await authed_global_admin.get(f"{BASE}/{org_id}")
        assert follow_up.status_code == 404

    async def test_delete_not_found_returns_404(self, authed_global_admin):
        resp = await authed_global_admin.delete(f"{BASE}/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_delete_forbidden_for_non_admin_of_org(
        self, authed_global_admin, auth_as, make_user_session_factory
    ):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]

        unrelated = auth_as(org_scoped_admin_session(make_user_session_factory))
        resp = await unrelated.delete(f"{BASE}/{org_id}")
        assert resp.status_code == 403


class TestUpdateOrgDocument:
    async def test_update_document_valid(self, authed_global_admin):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]
        resp = await authed_global_admin.patch(
            f"{BASE}/{org_id}/documents/fiscal",
            files={"file": ("fiscal.pdf", b"%PDF-1.4 contenido", "application/pdf")},
        )
        assert resp.status_code == 200
        assert resp.json()["fiscalDocumentFile"] is not None

    async def test_update_document_replaces_previous(self, authed_global_admin):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]
        first = await authed_global_admin.patch(
            f"{BASE}/{org_id}/documents/fiscal",
            files={"file": ("v1.pdf", b"%PDF-1.4 version 1", "application/pdf")},
        )
        second = await authed_global_admin.patch(
            f"{BASE}/{org_id}/documents/fiscal",
            files={"file": ("v2.pdf", b"%PDF-1.4 version 2", "application/pdf")},
        )
        assert second.status_code == 200
        assert first.json()["fiscalDocumentFile"] != second.json()["fiscalDocumentFile"]

    async def test_update_document_invalid_doc_type_returns_422(
        self, authed_global_admin
    ):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]
        resp = await authed_global_admin.patch(
            f"{BASE}/{org_id}/documents/not-a-real-type",
            files={"file": ("fiscal.pdf", b"contenido", "application/pdf")},
        )
        assert resp.status_code == 422

    async def test_update_document_forbidden_for_non_admin_of_org(
        self, authed_global_admin, auth_as, make_user_session_factory
    ):
        create = await authed_global_admin.post(f"{BASE}/", json=org_payload())
        org_id = create.json()["id"]

        unrelated = auth_as(org_scoped_admin_session(make_user_session_factory))
        resp = await unrelated.patch(
            f"{BASE}/{org_id}/documents/fiscal",
            files={"file": ("fiscal.pdf", b"contenido", "application/pdf")},
        )
        assert resp.status_code == 403
