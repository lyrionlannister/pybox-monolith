import uuid

import pytest

from core.database.redis import redis_client
from identity.users.enums.user_enums import (
    IdentityVerificationStatus,
    UserRole,
    UserScope,
)
from identity.users.schemas.user_session_schema import session_key
from tests.factories import (
    STRONG_PASSWORD,
    get_user_by_email,
    mark_mfa_verified,
    register_payload,
)

AUTH_BASE = "/api/v1/auth"
BASE = "/api/v1/users"


@pytest.fixture
async def real_user(client, db_session):
    """Registra un usuario real y deja el `client` autenticado vía cookie real
    (no `auth_as`): /me y /preferences/tours validan la sesión real en Redis."""
    payload = register_payload()
    resp = await client.post(f"{AUTH_BASE}/register/user", json=payload)
    assert resp.status_code == 201
    user = await get_user_by_email(db_session, payload["email"])
    await mark_mfa_verified(user.id)
    return user


class TestMe:
    async def test_me_valid(self, client, real_user):
        resp = await client.get(f"{BASE}/me")
        assert resp.status_code == 200
        assert resp.json()["userId"] == str(real_user.id)

    async def test_me_after_logout_does_not_revive_session(self, client, real_user):
        access_token = client.cookies.get("access_token")
        assert access_token
        logout = await client.post(f"{AUTH_BASE}/logout")
        assert logout.status_code == 200
        client.cookies.clear()
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = await client.get(f"{BASE}/me", headers=headers)
        assert resp.status_code == 401
        assert await redis_client.get(session_key(real_user.id)) is None
        tours = await client.get(f"{BASE}/me/preferences/tours", headers=headers)
        assert tours.status_code == 401

    async def test_me_without_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/me")
        assert resp.status_code == 401


class TestProfilePhoto:
    # Firma real de PNG: `verify_magic_bytes` (document_naming.py) exige que el
    # contenido empiece con los 8 bytes de la firma, no solo que diga ser PNG.
    PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

    async def test_upload_valid(self, client, real_user):
        resp = await client.put(
            f"{BASE}/me/profile-photo",
            files={
                "file": ("avatar.png", self.PNG_SIGNATURE + b"fake bytes", "image/png")
            },
        )
        assert resp.status_code == 200
        assert resp.json()["profilePhotoUrl"] is not None

    async def test_get_content_valid_after_upload(self, client, real_user):
        content = self.PNG_SIGNATURE + b"fake bytes"
        await client.put(
            f"{BASE}/me/profile-photo",
            files={"file": ("avatar.png", content, "image/png")},
        )

        resp = await client.get(f"{BASE}/{real_user.id}/profile-photo/content")
        assert resp.status_code == 200
        assert resp.content == content

    async def test_upload_replaces_previous_photo(self, client, real_user):
        first_content = self.PNG_SIGNATURE + b"primera foto"
        first = await client.put(
            f"{BASE}/me/profile-photo",
            files={"file": ("avatar.png", first_content, "image/png")},
        )
        assert first.status_code == 200

        second_content = self.PNG_SIGNATURE + b"segunda foto"
        second = await client.put(
            f"{BASE}/me/profile-photo",
            files={"file": ("avatar2.png", second_content, "image/png")},
        )
        assert second.status_code == 200

        resp = await client.get(f"{BASE}/{real_user.id}/profile-photo/content")
        assert resp.content == second_content

    async def test_get_content_without_photo_returns_404(self, client, real_user):
        resp = await client.get(f"{BASE}/{real_user.id}/profile-photo/content")
        assert resp.status_code == 404


class TestTourPreferences:
    async def test_get_tours_valid_empty(self, client, real_user):
        resp = await client.get(f"{BASE}/me/preferences/tours")
        assert resp.status_code == 200
        assert resp.json()["dismissedTours"] == []

    async def test_dismiss_tour_valid(self, client, real_user):
        resp = await client.post(
            f"{BASE}/me/preferences/tours/org-modules-tour-seen/dismiss"
        )
        assert resp.status_code == 200
        assert "org-modules-tour-seen" in resp.json()["dismissedTours"]

    async def test_dismiss_unknown_tour_returns_404(self, client, real_user):
        resp = await client.post(f"{BASE}/me/preferences/tours/not-a-real-tour/dismiss")
        assert resp.status_code == 404

    async def test_restore_tour_valid(self, client, real_user):
        await client.post(f"{BASE}/me/preferences/tours/org-modules-tour-seen/dismiss")
        resp = await client.post(
            f"{BASE}/me/preferences/tours/org-modules-tour-seen/restore"
        )
        assert resp.status_code == 200
        assert "org-modules-tour-seen" not in resp.json()["dismissedTours"]

    async def test_restore_all_tours_valid(self, client, real_user):
        await client.post(f"{BASE}/me/preferences/tours/org-modules-tour-seen/dismiss")
        resp = await client.post(f"{BASE}/me/preferences/tours/restore")
        assert resp.status_code == 200
        assert resp.json()["dismissedTours"] == []


class TestAvailableForChat:
    async def test_available_for_chat_valid(self, auth_as, make_user_session_factory):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.get(f"{BASE}/available-for-chat")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_available_for_chat_without_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/available-for-chat")
        assert resp.status_code == 401


class TestListUsers:
    async def test_list_valid_as_global_admin(self, auth_as, make_user_session_factory):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.get(f"{BASE}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_self_scope_returns_403(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.USER, scope=UserScope.SELF)
        )
        resp = await authed.get(f"{BASE}")
        assert resp.status_code == 403


class TestGetUser:
    async def test_get_valid_as_global_admin(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.get(f"{BASE}/{real_user.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(real_user.id)

    async def test_get_not_found_returns_404(self, auth_as, make_user_session_factory):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.get(f"{BASE}/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_get_forbidden_for_unrelated_self_scope(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.USER, scope=UserScope.SELF)
        )
        resp = await authed.get(f"{BASE}/{real_user.id}")
        assert resp.status_code == 403


class TestUpdateUser:
    async def test_update_valid_as_global_admin(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.patch(
            f"{BASE}/{real_user.id}", json={"firstname": "Nuevo Nombre"}
        )
        assert resp.status_code == 200
        assert resp.json()["firstname"] == "Nuevo Nombre"

    async def test_self_cannot_change_document_after_identity_approved(
        self, auth_as, make_user_session_factory, real_user, db_session
    ):
        real_user.identity_verification_status = IdentityVerificationStatus.APPROVED
        await db_session.flush()
        original_hash = real_user.document_number_hash
        authed = auth_as(
            make_user_session_factory(
                user_id=real_user.id, role=UserRole.USER, scope=UserScope.SELF
            )
        )
        resp = await authed.patch(
            f"{BASE}/{real_user.id}",
            json={"document_type": "CC", "document_number": "998877665"},
        )
        assert resp.status_code == 409
        await db_session.refresh(real_user)
        assert real_user.document_number_hash == original_hash

    async def test_self_unchanged_document_is_not_a_change(
        self, auth_as, make_user_session_factory, real_user, db_session
    ):
        real_user.identity_verification_status = IdentityVerificationStatus.APPROVED
        await db_session.flush()
        authed = auth_as(
            make_user_session_factory(
                user_id=real_user.id, role=UserRole.USER, scope=UserScope.SELF
            )
        )
        resp = await authed.patch(
            f"{BASE}/{real_user.id}",
            json={"firstname": "Ana", "document_type": real_user.document_type},
        )
        assert resp.status_code == 200
        await db_session.refresh(real_user)
        assert (
            real_user.identity_verification_status
            == IdentityVerificationStatus.APPROVED
        )

    async def test_admin_document_change_resets_identity_verification(
        self, auth_as, make_user_session_factory, real_user, db_session
    ):
        real_user.identity_verification_status = IdentityVerificationStatus.APPROVED
        await db_session.flush()
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.patch(
            f"{BASE}/{real_user.id}",
            json={"document_type": "CC", "document_number": "112233445"},
        )
        assert resp.status_code == 200
        await db_session.refresh(real_user)
        assert (
            real_user.identity_verification_status
            == IdentityVerificationStatus.NOT_SUBMITTED
        )

    async def test_update_not_found_returns_404(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.patch(f"{BASE}/{uuid.uuid4()}", json={"firstname": "x"})
        assert resp.status_code == 404

    async def test_update_forbidden_for_unrelated_self_scope(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.USER, scope=UserScope.SELF)
        )
        resp = await authed.patch(f"{BASE}/{real_user.id}", json={"firstname": "hack"})
        assert resp.status_code == 403

    async def test_email_already_taken_by_another_user_returns_409(
        self, client, auth_as, make_user_session_factory, real_user
    ):
        other_payload = register_payload()
        resp = await client.post(f"{AUTH_BASE}/register/user", json=other_payload)
        assert resp.status_code == 201

        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.patch(
            f"{BASE}/{real_user.id}", json={"email": other_payload["email"]}
        )
        assert resp.status_code == 409

    async def test_can_keep_its_own_email_unchanged(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.patch(
            f"{BASE}/{real_user.id}", json={"email": real_user.email}
        )
        assert resp.status_code == 200


class TestDeleteUser:
    async def test_delete_valid_as_global_admin(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.delete(f"{BASE}/{real_user.id}")
        assert resp.status_code == 204

    async def test_delete_self_returns_400(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = auth_as(
            make_user_session_factory(
                user_id=real_user.id, role=UserRole.ADMIN, scope=UserScope.GLOBAL
            )
        )
        resp = await authed.delete(f"{BASE}/{real_user.id}")
        assert resp.status_code == 400

    async def test_delete_forbidden_for_unrelated_self_scope(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.USER, scope=UserScope.SELF)
        )
        resp = await authed.delete(f"{BASE}/{real_user.id}")
        assert resp.status_code == 403


class TestSelfSensitiveChanges:
    """Con una sesión robada no debe poder cambiarse el correo (destino de la
    recuperación de contraseña) ni desactivarse el MFA sin la contraseña actual."""

    def _self(self, auth_as, make_user_session_factory, user):
        return auth_as(
            make_user_session_factory(
                user_id=user.id, role=UserRole.USER, scope=UserScope.SELF
            )
        )

    async def test_email_change_without_password_is_rejected(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = self._self(auth_as, make_user_session_factory, real_user)
        resp = await authed.patch(
            f"{BASE}/{real_user.id}", json={"email": f"{uuid.uuid4()}@example.com"}
        )
        assert resp.status_code == 403

    async def test_email_change_with_password_marks_it_unverified(
        self, auth_as, make_user_session_factory, real_user, db_session
    ):
        real_user.is_email_verified = True
        await db_session.flush()
        authed = self._self(auth_as, make_user_session_factory, real_user)
        new_email = f"{uuid.uuid4()}@example.com"
        resp = await authed.patch(
            f"{BASE}/{real_user.id}",
            json={"email": new_email, "currentPassword": STRONG_PASSWORD},
        )
        assert resp.status_code == 200
        await db_session.refresh(real_user)
        assert real_user.email == new_email
        assert real_user.is_email_verified is False

    async def test_disabling_mfa_requires_password(
        self, auth_as, make_user_session_factory, real_user, db_session
    ):
        real_user.mfa_enabled = True
        await db_session.flush()
        authed = self._self(auth_as, make_user_session_factory, real_user)
        resp = await authed.patch(f"{BASE}/{real_user.id}", json={"mfaEnabled": False})
        assert resp.status_code == 403
        ok = await authed.patch(
            f"{BASE}/{real_user.id}",
            json={"mfaEnabled": False, "currentPassword": STRONG_PASSWORD},
        )
        assert ok.status_code == 200

    async def test_cannot_deactivate_own_account(
        self, auth_as, make_user_session_factory, real_user
    ):
        authed = self._self(auth_as, make_user_session_factory, real_user)
        resp = await authed.patch(f"{BASE}/{real_user.id}", json={"isActive": False})
        assert resp.status_code == 403
