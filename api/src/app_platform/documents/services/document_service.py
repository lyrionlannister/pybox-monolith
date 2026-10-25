"""Subida, descarga y borrado de documentos contra el almacén de objetos."""

import uuid
from typing import Optional
from urllib.parse import quote

from fastapi import HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.documents.enums.document_enums import MAX_DOCUMENT_SIZE_BYTES
from app_platform.documents.models.document_model import DocumentModel
from app_platform.documents.repository.document_repository import DocumentRepository
from app_platform.documents.schemas.document_schemas import DocumentResponse
from app_platform.documents.utils.document_naming import (
    build_object_key,
    checksum,
    resolve_content_type,
    safe_original_name,
    verify_magic_bytes,
)
from core.config.logger import logger
from core.storage.object_storage import ObjectStorage, ObjectStorageError
from core.storage.s3_object_storage import object_storage


class DocumentService:
    """Dueño de todo lo que entra y sale del almacén de objetos.

    La API es el único cliente del almacén: lo alcanza por la red privada del compose,
    que no está publicada en ningún puerto. Ningún otro módulo habla con
    `object_storage`: los que necesitan guardar un archivo delegan en este service. Eso
    deja una sola puerta, y con ella un solo lugar donde auditar.

    Este service NO decide de quién es el documento ni quién puede leerlo: solo sabe de
    archivos. La pertenencia la declara el Service de dominio insertando su fila en la
    tabla de unión correspondiente (`documentos_deudor`, `documentos_ticket`, …), y la
    autorización la resuelve ese mismo Service ANTES de llamar acá — igual que antes de
    este cambio.
    """

    def __init__(
        self,
        session: AsyncSession,
        storage: Optional[ObjectStorage] = None,
    ) -> None:
        self._repo = DocumentRepository(session)
        # Se inyecta la interfaz, no la implementación: los tests pueden pasar un doble
        # y cambiar de backend no toca este archivo.
        self._storage = storage or object_storage

    # ── Escritura (API para otros módulos) ───────────────────────────────────

    async def store(
        self,
        file: UploadFile,
        domain: str,
        owner_id: str,
        uploaded_by: Optional[uuid.UUID] = None,
        organization_id: Optional[uuid.UUID] = None,
    ) -> DocumentModel:
        """Valida y guarda un archivo subido por un usuario.

        No decide *si* el llamador puede subirlo: esa autorización es del service que
        conoce el recurso (soporte sabe de tickets, organizaciones de entidades). Acá se
        garantiza que lo que se guarda es de un tipo permitido y no excede el límite.

        Tampoco deduplica: si el dominio quiere reusar un archivo idéntico ya guardado,
        consulta el `get_by_checksum` de SU propio repository antes de llamar acá. La
        dedup necesita saber de quién es el documento, y eso ya no se sabe en esta capa.
        """
        content = await file.read()
        content_type = resolve_content_type(file.filename, file.content_type)
        if content:
            verify_magic_bytes(content, content_type)

        if not content:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "El archivo está vacío"
            )
        if len(content) > MAX_DOCUMENT_SIZE_BYTES:
            limit_mb = MAX_DOCUMENT_SIZE_BYTES // (1024 * 1024)
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"El archivo supera el límite de {limit_mb} MB",
            )

        return await self._persist(
            content=content,
            filename=file.filename,
            content_type=content_type,
            domain=domain,
            owner_id=owner_id,
            uploaded_by=uploaded_by,
            organization_id=organization_id,
        )

    async def store_generated(
        self,
        content: bytes,
        filename: str,
        content_type: str,
        domain: str,
        owner_id: str,
        uploaded_by: Optional[uuid.UUID] = None,
        organization_id: Optional[uuid.UUID] = None,
    ) -> DocumentModel:
        """Guarda un artefacto que produjo la propia API (un CSV de reporte, la
        exportación de un segmento, el archivo fuente de una carga ya parseada).

        Se salta la lista blanca de subidas a propósito: esa lista acota lo que un
        usuario puede empujar al almacén, y el content-type de estos lo fija el código
        que genera el archivo. Tampoco deduplica: cada ejecución debe quedar con su
        propia fila aunque el resultado no haya cambiado.
        """
        return await self._persist(
            content=content,
            filename=filename,
            content_type=content_type,
            domain=domain,
            owner_id=owner_id,
            uploaded_by=uploaded_by,
            organization_id=organization_id,
        )

    # ── Lectura ──────────────────────────────────────────────────────────────

    async def get_by_id(self, document_id: uuid.UUID) -> Optional[DocumentModel]:
        """Metadatos de un documento por id, sin ninguna comprobación de pertenencia.

        Solo para llamadores que YA validaron el ownership por otro camino: los casos
        1:1, donde el id salió de la propia fila autorizada (`entidades.id_documento_*`,
        `usuarios.id_documento_foto_perfil`, `extractos.id_documento`).
        """
        return await self._repo.get_by_id(document_id)

    async def to_content_response(
        self, document: DocumentModel, requested_by: Optional[uuid.UUID] = None
    ) -> Response:
        """Trae el archivo del almacén y lo devuelve al cliente.

        El llamador ya validó el ownership. `inline` para que el visor del front lo
        muestre sin descargar, y el nombre en `filename*` por RFC 5987 para que tildes y
        espacios no rompan la cabecera. `no-store` porque un intermediario no debería
        quedarse con una copia de un documento de identidad.
        """
        try:
            content = await self._storage.get(document.object_key)
        except ObjectStorageError as error:
            logger.error(
                "[documents] fallo al leer | id=%s error=%s", document.id, error
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "No se pudo recuperar el documento"
            ) from error

        logger.info(
            "[documents] entregado | id=%s solicitante=%s bytes=%s",
            document.id,
            requested_by,
            len(content),
        )
        return Response(
            content=content,
            media_type=document.content_type,
            headers={
                "Content-Disposition": (
                    f"inline; filename*=UTF-8''{quote(document.original_name)}"
                ),
                "Cache-Control": "no-store, private",
            },
        )

    # ── Baja y restauración de la fila `documentos` ──────────────────────────

    async def delete(self, document: DocumentModel) -> None:
        """Da de baja la fila de metadatos. El llamador ya validó el ownership.

        Solo soft delete: el objeto en el almacén NO se toca acá. El borrado físico
        queda para un proceso de purga aparte (fuera del alcance de este módulo), que
        recorre las filas con `eliminado_en` vencido y recién ahí borra los bytes. Por
        eso `restore()` alcanza con limpiar `eliminado_en`: los bytes siguen estando.
        """
        await self._repo.delete(document)

    async def delete_by_id(self, document_id: uuid.UUID) -> None:
        """Baja de un documento del que el llamador ya es dueño por construcción — el
        caso de sustituir un documento cuyo id venía de la propia fila que se edita."""
        document = await self._repo.get_by_id(document_id)
        if document is not None:
            await self.delete(document)

    async def restore(self, document: DocumentModel) -> None:
        """Deshace el soft delete. No hay nada que recuperar del almacén porque
        `delete()` nunca borró el objeto."""
        await self._repo.restore(document)

    async def restore_by_id(self, document_id: uuid.UUID) -> None:
        document = await self._repo.get_by_id_including_deleted(document_id)
        if document is not None:
            await self.restore(document)

    # ── Internos ─────────────────────────────────────────────────────────────

    async def _persist(
        self,
        content: bytes,
        filename: str | None,
        content_type: str,
        domain: str,
        owner_id: str,
        uploaded_by: Optional[uuid.UUID],
        organization_id: Optional[uuid.UUID],
    ) -> DocumentModel:
        original_name = safe_original_name(filename)
        digest = checksum(content)

        object_key = build_object_key(domain, owner_id, original_name)
        try:
            etag = await self._storage.put(object_key, content, content_type)
        except ObjectStorageError as error:
            logger.error(
                "[documents] fallo al subir | key=%s error=%s", object_key, error
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "No se pudo guardar el documento"
            ) from error

        document = DocumentModel(
            object_key=object_key,
            organization_id=organization_id,
            original_name=original_name,
            content_type=content_type,
            size_bytes=len(content),
            checksum=digest,
            etag=etag,
            uploaded_by=uploaded_by,
        )
        try:
            created = await self._repo.add(document)
        except Exception:
            # Sin la fila, el objeto quedaría inalcanzable y ocupando espacio.
            await self._safe_delete_object(object_key)
            raise

        logger.info(
            "[documents] guardado | id=%s dominio=%s dueno=%s bytes=%s",
            created.id,
            domain,
            owner_id,
            len(content),
        )
        return created

    async def _safe_delete_object(self, object_key: str) -> None:
        """Borra el objeto sin dejar que su fallo tumbe la operación que lo pidió: si
        falla, se registra para reconciliar después y se sigue.

        Queda para el rollback de `_persist` (objeto subido cuya fila no se pudo
        insertar) y para el futuro proceso de purga. `delete()` ya no lo llama.
        """
        try:
            await self._storage.delete(object_key)
        except ObjectStorageError as error:
            logger.error(
                "[documents] objeto huérfano | key=%s error=%s", object_key, error
            )

    @staticmethod
    def to_response(document: DocumentModel) -> DocumentResponse:
        return DocumentResponse(
            id=document.id,
            original_name=document.original_name,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            checksum=document.checksum,
            created_at=document.created_at,
        )
