"""Tests de `DocumentService` con un `ObjectStorage` falso en memoria (implementa el
mismo contrato ABC, ver `core/storage/object_storage.py`) y `db_session` real.

Reescrito tras el refactor de Fase 2 (separación de la asociación polimórfica de
`documentos`, ver `document_model.py`): el service ya no maneja subida en dos fases
(`create_upload_ticket`/`confirm`) ni URLs firmadas -- ahora `store`/`store_generated`
leen el archivo directo y lo guardan en el mismo paso. Tampoco resuelve pertenencia
(`get_owned_by`/`list_by_owners` con `owner_scope`/`category` desaparecieron): eso
ahora vive en el repository de cada dominio (`documentos_deudor`, `documentos_ticket`,
...), que este archivo ya no cubre -- ver `test_document_controller.py` para el flujo
feliz end-to-end contra el storage real.
"""

import uuid

import pytest
from fastapi import HTTPException, UploadFile

from app_platform.documents.enums.document_enums import MAX_DOCUMENT_SIZE_BYTES
from app_platform.documents.models.document_model import DocumentModel
from app_platform.documents.services.document_service import DocumentService
from core.storage.object_storage import (
    ObjectMetadata,
    ObjectStorage,
    ObjectStorageError,
)

# Firma real de PDF: `verify_magic_bytes` (document_naming.py) exige que el
# contenido empiece así, no solo que la extensión sea .pdf.
PDF_CONTENT = b"%PDF-1.4 contenido real"


class FakeObjectStorage(ObjectStorage):
    """Guarda objetos en un dict en memoria."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}
        self.deleted_keys: list[str] = []
        self.put_should_fail = False
        self.get_should_fail = False

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        if self.put_should_fail:
            raise ObjectStorageError("simulated put failure")
        self._objects[key] = (data, content_type)
        return f"etag-{len(data)}"

    async def get(self, key: str) -> bytes:
        if self.get_should_fail:
            raise ObjectStorageError("simulated get failure")
        data, _content_type = self._objects[key]
        return data

    async def head(self, key: str) -> ObjectMetadata | None:
        entry = self._objects.get(key)
        if entry is None:
            return None
        data, content_type = entry
        return ObjectMetadata(
            size_bytes=len(data), content_type=content_type, etag=f"etag-{len(data)}"
        )

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)
        self.deleted_keys.append(key)


def upload_file(
    filename: str, content: bytes, content_type: str | None = None
) -> UploadFile:
    import io

    headers = {"content-type": content_type} if content_type else {}
    return UploadFile(filename=filename, file=io.BytesIO(content), headers=headers)


@pytest.fixture
def fake_storage() -> FakeObjectStorage:
    return FakeObjectStorage()


@pytest.fixture
def service(db_session, fake_storage) -> DocumentService:
    return DocumentService(db_session, storage=fake_storage)


class TestStore:
    async def test_valid_upload_persists_document_and_object(
        self, service: DocumentService, fake_storage: FakeObjectStorage
    ):
        document = await service.store(
            upload_file("cedula.pdf", PDF_CONTENT),
            domain="deudor",
            owner_id=str(uuid.uuid4()),
        )

        assert document.content_type == "application/pdf"
        assert document.size_bytes == len(PDF_CONTENT)
        assert document.etag
        assert document.object_key in fake_storage._objects
        assert document.object_key.startswith("deudor/")

    async def test_empty_file_raises_422(self, service: DocumentService):
        with pytest.raises(HTTPException) as exc_info:
            await service.store(
                upload_file("vacio.pdf", b""),
                domain="deudor",
                owner_id=str(uuid.uuid4()),
            )
        assert exc_info.value.status_code == 422

    async def test_oversized_file_raises_413(self, service: DocumentService):
        content = b"%PDF-1.4" + b"x" * (MAX_DOCUMENT_SIZE_BYTES + 1)
        with pytest.raises(HTTPException) as exc_info:
            await service.store(
                upload_file("grande.pdf", content),
                domain="deudor",
                owner_id=str(uuid.uuid4()),
            )
        assert exc_info.value.status_code == 413

    async def test_unsupported_extension_raises_415(self, service: DocumentService):
        with pytest.raises(HTTPException) as exc_info:
            await service.store(
                upload_file("script.exe", b"contenido"),
                domain="deudor",
                owner_id=str(uuid.uuid4()),
            )
        assert exc_info.value.status_code == 415

    async def test_storage_failure_raises_503_and_no_row_persisted(
        self, service: DocumentService, fake_storage: FakeObjectStorage, db_session
    ):
        fake_storage.put_should_fail = True
        with pytest.raises(HTTPException) as exc_info:
            await service.store(
                upload_file("cedula.pdf", PDF_CONTENT),
                domain="deudor",
                owner_id=str(uuid.uuid4()),
            )
        assert exc_info.value.status_code == 503

    async def test_rollback_deletes_object_when_row_insert_fails(
        self, service: DocumentService, fake_storage: FakeObjectStorage, monkeypatch
    ):
        async def _boom(_document):
            raise RuntimeError("simulated insert failure")

        monkeypatch.setattr(service._repo, "add", _boom)

        with pytest.raises(RuntimeError):
            await service.store(
                upload_file("cedula.pdf", PDF_CONTENT),
                domain="deudor",
                owner_id=str(uuid.uuid4()),
            )

        # El objeto no debe quedar huérfano en el almacén si la fila nunca se creó.
        assert len(fake_storage._objects) == 0
        assert len(fake_storage.deleted_keys) == 1


class TestStoreGenerated:
    async def test_creates_document_with_correct_size(
        self, service: DocumentService, fake_storage: FakeObjectStorage
    ):
        content = b"col1,col2\nval1,val2\n"
        document = await service.store_generated(
            content=content,
            filename="reporte.csv",
            content_type="text/csv",
            domain="reporte",
            owner_id=str(uuid.uuid4()),
        )
        assert document.size_bytes == len(content)
        assert document.etag
        assert document.object_key in fake_storage._objects

    async def test_storage_failure_raises_503(
        self, service: DocumentService, fake_storage: FakeObjectStorage
    ):
        fake_storage.put_should_fail = True
        with pytest.raises(HTTPException) as exc_info:
            await service.store_generated(
                content=b"data",
                filename="reporte.csv",
                content_type="text/csv",
                domain="reporte",
                owner_id=str(uuid.uuid4()),
            )
        assert exc_info.value.status_code == 503


class TestGetById:
    async def test_returns_document_when_it_exists(self, service: DocumentService):
        document = await service.store_generated(
            content=b"data",
            filename="a.csv",
            content_type="text/csv",
            domain="reporte",
            owner_id=str(uuid.uuid4()),
        )
        found = await service.get_by_id(document.id)
        assert found is not None
        assert found.id == document.id

    async def test_returns_none_when_it_does_not_exist(self, service: DocumentService):
        assert await service.get_by_id(uuid.uuid4()) is None


class TestToContentResponse:
    async def test_returns_response_with_content_and_headers(
        self, service: DocumentService
    ):
        document = await service.store(
            upload_file("cédula depósito.pdf", PDF_CONTENT),
            domain="deudor",
            owner_id=str(uuid.uuid4()),
        )
        response = await service.to_content_response(document)
        assert response.body == PDF_CONTENT
        assert response.media_type == "application/pdf"
        assert "inline" in response.headers["Content-Disposition"]

    async def test_storage_failure_raises_503(
        self, service: DocumentService, fake_storage: FakeObjectStorage
    ):
        document = await service.store(
            upload_file("cedula.pdf", PDF_CONTENT),
            domain="deudor",
            owner_id=str(uuid.uuid4()),
        )
        fake_storage.get_should_fail = True
        with pytest.raises(HTTPException) as exc_info:
            await service.to_content_response(document)
        assert exc_info.value.status_code == 503


class TestDeleteAndRestore:
    async def test_delete_soft_deletes_row_without_touching_the_object(
        self, service: DocumentService, fake_storage: FakeObjectStorage, db_session
    ):
        document = await service.store(
            upload_file("cedula.pdf", PDF_CONTENT),
            domain="deudor",
            owner_id=str(uuid.uuid4()),
        )

        await service.delete(document)

        row = await db_session.get(DocumentModel, document.id)
        assert row is not None and row.deleted_at is not None
        # El objeto físico NO se borra: el borrado físico queda para un proceso de
        # purga aparte (ver docstring de `DocumentService.delete`).
        assert document.object_key in fake_storage._objects
        assert fake_storage.deleted_keys == []

    async def test_delete_by_id_on_nonexistent_id_is_a_noop(
        self, service: DocumentService
    ):
        await service.delete_by_id(uuid.uuid4())

    async def test_restore_clears_deleted_at(
        self, service: DocumentService, db_session
    ):
        document = await service.store(
            upload_file("cedula.pdf", PDF_CONTENT),
            domain="deudor",
            owner_id=str(uuid.uuid4()),
        )
        await service.delete(document)

        await service.restore_by_id(document.id)

        row = await db_session.get(DocumentModel, document.id)
        assert row is not None and row.deleted_at is None

    async def test_restore_by_id_on_nonexistent_id_is_a_noop(
        self, service: DocumentService
    ):
        await service.restore_by_id(uuid.uuid4())


class TestToResponse:
    async def test_maps_model_fields_to_schema(self, service: DocumentService):
        document = await service.store(
            upload_file("cedula.pdf", PDF_CONTENT),
            domain="deudor",
            owner_id=str(uuid.uuid4()),
        )
        response = DocumentService.to_response(document)
        assert response.id == document.id
        assert response.original_name == document.original_name
        assert response.content_type == document.content_type
        assert response.size_bytes == document.size_bytes
        assert response.checksum == document.checksum
