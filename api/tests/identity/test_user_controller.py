import uuid

import pytest

from identity.users.enums.user_enums import UserRole, UserScope
from tests.factories import get_user_by_email, mark_mfa_verified, register_payload

AUTH_BASE = "/api/v1/auth"
BASE = "/api/v1/users"


@pytest.fixture
async def real_user(client, db_session):
    """Registra un usuario real y deja el `client` autenticado vía cookie real
    (no `auth_as`): /me y /preferences/tours usan `TokenPayload`, JWT real."""
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
