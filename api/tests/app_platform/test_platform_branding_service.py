"""Tests de `PlatformBrandingService`.

`DocumentService.to_content_response` no valida pertenencia (asume que el llamador ya
lo hizo), así que la única barrera del endpoint `GET /platform/branding/documents/{id}/content`
es que `get_logo_content` responda solo por el documento que es EXACTAMENTE el logo
vigente. Estos tests fijan ese contrato (IDOR) y que reemplazar el logo no deje a la
plataforma sin ninguno si la subida falla.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app_platform.branding.services.platform_branding_service import (
    PLATFORM_BRANDING_OWNER_ID,
    PLATFORM_BRANDING_STORAGE_DOMAIN,
    PlatformBrandingService,
)


def _branding(logo_document_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(logo_document_id=logo_document_id)


def _service(branding) -> tuple[PlatformBrandingService, MagicMock, MagicMock]:
    repo = MagicMock()
    repo.get_singleton = AsyncMock(return_value=branding)
    repo.update = AsyncMock(side_effect=lambda instance: instance)
    documents = MagicMock()
    documents.get_by_id = AsyncMock()
    documents.to_content_response = AsyncMock()
    documents.store = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    documents.delete_by_id = AsyncMock()
    return (
        PlatformBrandingService(repo=repo, document_service=documents),
        repo,
        documents,
    )


class TestGetSingleton:
    async def test_missing_row_raises_500(self):
        service, _, _ = _service(None)

        with pytest.raises(HTTPException) as exc:
            await service.get_singleton()

        assert exc.value.status_code == 500


class TestGetLogoContent:
    async def test_returns_content_when_document_is_the_current_logo(self):
        logo_id = uuid.uuid4()
        requested_by = uuid.uuid4()
        service, _, documents = _service(_branding(logo_id))
        document = SimpleNamespace(id=logo_id)
        documents.get_by_id.return_value = document
        documents.to_content_response.return_value = "respuesta"

        result = await service.get_logo_content(logo_id, requested_by)

        assert result == "respuesta"
        documents.to_content_response.assert_awaited_once_with(document, requested_by)

    async def test_other_document_id_is_404_and_never_reads_the_document(self):
        service, _, documents = _service(_branding(uuid.uuid4()))

        with pytest.raises(HTTPException) as exc:
            await service.get_logo_content(uuid.uuid4(), uuid.uuid4())

        assert exc.value.status_code == 404
        documents.get_by_id.assert_not_awaited()
        documents.to_content_response.assert_not_awaited()

    async def test_no_logo_configured_is_404(self):
        service, _, documents = _service(_branding(None))

        with pytest.raises(HTTPException) as exc:
            await service.get_logo_content(uuid.uuid4(), uuid.uuid4())

        assert exc.value.status_code == 404
        documents.get_by_id.assert_not_awaited()

    async def test_logo_pointing_to_a_missing_document_is_404(self):
        logo_id = uuid.uuid4()
        service, _, documents = _service(_branding(logo_id))
        documents.get_by_id.return_value = None

        with pytest.raises(HTTPException) as exc:
            await service.get_logo_content(logo_id, uuid.uuid4())

        assert exc.value.status_code == 404
        documents.to_content_response.assert_not_awaited()


class TestReplaceLogo:
    async def test_stores_new_logo_points_to_it_and_deletes_previous_last(self):
        previous_id = uuid.uuid4()
        uploaded_by = uuid.uuid4()
        branding = _branding(previous_id)
        service, repo, documents = _service(branding)
        new_document = SimpleNamespace(id=uuid.uuid4())
        documents.store.return_value = new_document
        file = SimpleNamespace(filename="logo.png")
        order: list[str] = []

        async def record_update(instance):
            order.append("update")
            return instance

        async def record_delete(document_id):
            order.append("delete")

        repo.update.side_effect = record_update
        documents.delete_by_id.side_effect = record_delete

        result = await service.replace_logo(file, uploaded_by)

        assert result.logo_document_id == new_document.id
        assert order == ["update", "delete"]
        documents.delete_by_id.assert_awaited_once_with(previous_id)
        kwargs = documents.store.await_args.kwargs
        assert kwargs["file"] is file
        assert kwargs["domain"] == PLATFORM_BRANDING_STORAGE_DOMAIN
        assert kwargs["owner_id"] == PLATFORM_BRANDING_OWNER_ID
        assert kwargs["uploaded_by"] == uploaded_by

    async def test_first_logo_has_nothing_to_delete(self):
        service, _, documents = _service(_branding(None))

        await service.replace_logo(SimpleNamespace(filename="logo.png"), uuid.uuid4())

        documents.delete_by_id.assert_not_awaited()

    async def test_failed_upload_keeps_the_previous_logo(self):
        previous_id = uuid.uuid4()
        branding = _branding(previous_id)
        service, repo, documents = _service(branding)
        documents.store.side_effect = HTTPException(503, "almacén no disponible")

        with pytest.raises(HTTPException):
            await service.replace_logo(
                SimpleNamespace(filename="logo.png"), uuid.uuid4()
            )

        assert branding.logo_document_id == previous_id
        repo.update.assert_not_awaited()
        documents.delete_by_id.assert_not_awaited()


class TestToResponse:
    def test_no_logo_has_no_url(self):
        response = PlatformBrandingService.to_response(_branding(None))

        assert response.logo_url is None

    def test_logo_url_points_to_the_content_route(self):
        logo_id = uuid.uuid4()

        response = PlatformBrandingService.to_response(_branding(logo_id))

        assert response.logo_url == f"/platform/branding/documents/{logo_id}/content"
