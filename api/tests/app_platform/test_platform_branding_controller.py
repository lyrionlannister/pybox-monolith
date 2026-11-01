"""Autorización y validaciones del controller de branding de plataforma: solo un
administrador GLOBAL reemplaza el logo (ni el staff global que no es admin, ni un
admin de organización), y un archivo que no es imagen se rechaza antes de tocar el
service."""

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from app_platform.branding.controllers.platform_branding_controller import (
    update_platform_logo,
)
from app_platform.branding.services.platform_branding_service import (
    PlatformBrandingService,
)
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_session_schema import UserSession


def _session(role: UserRole, scope: UserScope) -> UserSession:
    return UserSession(
        user_id=uuid.uuid4(),
        full_name="Test User",
        email="test@example.com",
        role=role,
        scope=scope,
    )


def _file(filename: str = "logo.png") -> UploadFile:
    return UploadFile(file=io.BytesIO(b"contenido"), filename=filename)


def _service() -> MagicMock:
    service = MagicMock()
    service.replace_logo = AsyncMock()
    service.to_response = PlatformBrandingService.to_response
    return service


@pytest.mark.parametrize(
    "role, scope",
    [
        (UserRole.CUSTOMER_SERVICE, UserScope.GLOBAL),  # staff global que no es admin
        (
            UserRole.ADMIN,
            UserScope.ORGANIZATION,
        ),  # admin, pero solo de una organización
        (UserRole.USER, UserScope.SELF),
    ],
)
async def test_only_a_global_admin_can_replace_the_logo(role, scope):
    service = _service()

    with pytest.raises(HTTPException) as exc:
        await update_platform_logo(
            session=_session(role, scope), service=service, file=_file()
        )

    assert exc.value.status_code == 403
    service.replace_logo.assert_not_awaited()


async def test_a_pdf_is_rejected_with_415_before_touching_the_service():
    service = _service()

    with pytest.raises(HTTPException) as exc:
        await update_platform_logo(
            session=_session(UserRole.ADMIN, UserScope.GLOBAL),
            service=service,
            file=_file("logo.pdf"),
        )

    assert exc.value.status_code == 415
    service.replace_logo.assert_not_awaited()


async def test_a_global_admin_replaces_the_logo():
    session = _session(UserRole.ADMIN, UserScope.GLOBAL)
    logo_id = uuid.uuid4()
    service = _service()
    service.replace_logo.return_value = SimpleNamespace(logo_document_id=logo_id)

    response = await update_platform_logo(
        session=session, service=service, file=_file("logo.png")
    )

    service.replace_logo.assert_awaited_once()
    kwargs = service.replace_logo.await_args.kwargs
    assert kwargs["file"].filename == "logo.png"
    assert kwargs["uploaded_by"] == session.user_id
    assert response.logo_url == f"/platform/branding/documents/{logo_id}/content"
