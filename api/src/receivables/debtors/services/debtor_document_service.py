"""Subida, descarga y borrado de documentos del repositorio de un deudor."""

import uuid
from typing import Optional, Sequence

from fastapi import HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import UserDocumentType
from app_platform.documents.models.document_model import DocumentModel
from app_platform.documents.schemas.document_schemas import DocumentCategoryOption
from app_platform.documents.services.document_service import DocumentService
from app_platform.documents.utils.document_naming import checksum as compute_checksum
from core.security.policies.security_policies import (
    get_self_identity,
    require_verified_identity,
)
from identity.users.schemas.user_session_schema import UserSession
from receivables.debtors.enums.debtor_document_enums import (
    DEBTOR_DOCUMENT_CATEGORY_LABELS,
    SELF_UPLOADABLE_DEBTOR_CATEGORIES,
    DebtorDocumentCategory,
)
from receivables.debtors.models.debtor_document_model import DebtorDocumentModel
from receivables.debtors.models.debtor_model import DebtorModel
from receivables.debtors.repository.debtor_document_repository import (
    DEBTOR_DOCUMENT_STORAGE_DOMAIN,
    DebtorDocumentRepository,
)
from receivables.debtors.repository.debtor_repository import DebtorRepository
from receivables.debtors.schemas.debtor_document_schemas import (
    DebtorDocumentListResponse,
    DebtorDocumentResponse,
)


class DebtorDocumentService:
    """Repositorio documental del titular (scope SELF).

    La autorización no cambió con la migración de esquema: el gate SELF se aplica en el
    borde (`RequireSelf` en las rutas) y acá el deudor se resuelve SIEMPRE desde la
    identidad de la sesión (`get_self_identity`), nunca desde un id de path. El titular
    no puede nombrar a otro deudor.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._repo = DebtorDocumentRepository(session)
        self._debtor_repo = DebtorRepository(session)
        # Los bytes los guarda el módulo de documentos: ningún dominio habla con el
        # almacén directamente.
        self._document_service = DocumentService(session)

    # ── Catálogo ─────────────────────────────────────────────────────────────

    def list_categories(self) -> list[DocumentCategoryOption]:
        """Catálogo de categorías del ámbito deudor. Cada dominio expone el suyo: el
        catálogo único global (`GET /documents/categories`) desapareció con el enum."""
        return [
            DocumentCategoryOption(
                value=category.value, label=DEBTOR_DOCUMENT_CATEGORY_LABELS[category]
            )
            for category in DebtorDocumentCategory
        ]

    # ── Portal del titular ───────────────────────────────────────────────────

    async def list_mine(
        self, session: UserSession, category: Optional[DebtorDocumentCategory] = None
    ) -> DebtorDocumentListResponse:
        debtors = await self._require_self_debtors(session)
        rows: list[tuple[DebtorDocumentModel, DocumentModel]] = []
        for debtor in debtors:
            rows.extend(await self._repo.list_by_debtor(debtor.id, category))
        rows.sort(key=lambda row: row[1].created_at, reverse=True)
        return self.to_list_response(rows)

    async def upload_mine(
        self, session: UserSession, file: UploadFile, category: DebtorDocumentCategory
    ) -> DebtorDocumentResponse:
        if category not in SELF_UPLOADABLE_DEBTOR_CATEGORIES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "No puedes subir documentos de esa categoría",
            )
        # Los documentos del titular (p. ej. su identidad) son suyos, no de una
        # empresa: se guardan en su fila de deudor más antigua y se leen desde
        # cualquiera de ellas.
        debtors = await self._require_self_debtors(session)
        link, document = await self.store_for_debtor(
            debtor_id=debtors[0].id,
            file=file,
            category=category,
            uploaded_by=session.user_id,
        )
        return self.to_response(link, document)

    async def get_mine_content(
        self, session: UserSession, document_id: uuid.UUID
    ) -> Response:
        debtors = await self._require_self_debtors(session)
        _, document = await self._require_owned_by_any(debtors, document_id)
        return await self._document_service.to_content_response(
            document, session.user_id
        )

    async def delete_mine(self, session: UserSession, document_id: uuid.UUID) -> None:
        debtors = await self._require_self_debtors(session)
        link, document = await self._require_owned_by_any(debtors, document_id)
        await self.delete(link, document)

    # ── API para otros Services del dominio (ya autorizados) ─────────────────

    async def store_for_debtor(
        self,
        debtor_id: uuid.UUID,
        file: UploadFile,
        category: DebtorDocumentCategory,
        uploaded_by: Optional[uuid.UUID] = None,
        organization_id: Optional[uuid.UUID] = None,
    ) -> tuple[DebtorDocumentModel, DocumentModel]:
        """Guarda el archivo y lo enlaza al deudor, deduplicando por checksum.

        La dedup dejó de ser automática dentro de `DocumentService` (ya no sabe de quién
        es un documento): se consulta acá, contra el repo del dominio, antes de subir
        nada. Si el deudor ya tiene un archivo con ese contenido y esa categoría, se
        reutiliza esa fila.
        """
        content = await file.read()
        await file.seek(0)
        existing = await self._repo.get_by_checksum(
            debtor_id, compute_checksum(content)
        )
        if existing is not None and existing.category == category:
            document = await self._document_service.get_by_id(existing.document_id)
            if document is not None:
                return existing, document

        document = await self._document_service.store(
            file=file,
            domain=DEBTOR_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(debtor_id),
            uploaded_by=uploaded_by,
            organization_id=organization_id,
        )
        link = await self._repo.add(
            DebtorDocumentModel(
                debtor_id=debtor_id,
                category=category,
                document_id=document.id,
            )
        )
        return link, document

    async def list_for_debtor(
        self, debtor_id: uuid.UUID, category: Optional[DebtorDocumentCategory] = None
    ) -> Sequence[tuple[DebtorDocumentModel, DocumentModel]]:
        """Documentos de un deudor. El llamador ya validó que puede verlos (el lado
        entidad lo hace contra el portafolio, en `DebtorService`)."""
        return await self._repo.list_by_debtor(debtor_id, category)

    async def require_owned(
        self, debtor_id: uuid.UUID, document_id: uuid.UUID
    ) -> tuple[DebtorDocumentModel, DocumentModel]:
        """Documento acotado a su deudor. Un id que no le pertenece responde 404,
        no 403: no se le confirma a quien pregunta que el documento existe."""
        row = await self._repo.get_owned(debtor_id, document_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado")
        return row

    async def delete(self, link: DebtorDocumentModel, document: DocumentModel) -> None:
        """Da de baja el enlace y la fila `documentos`, en la misma unidad de trabajo.

        Solo soft delete: los bytes no se tocan. El borrado físico queda para el proceso
        de purga (fuera de este alcance), y por eso `restore()` alcanza con limpiar
        `eliminado_en` en las dos filas.
        """
        await self._repo.delete(link)
        await self._document_service.delete(document)

    async def restore(self, link: DebtorDocumentModel) -> None:
        await self._repo.restore(link)
        await self._document_service.restore_by_id(link.document_id)

    # ── Internos ─────────────────────────────────────────────────────────────

    async def _require_owned_by_any(
        self, debtors: Sequence[DebtorModel], document_id: uuid.UUID
    ) -> tuple[DebtorDocumentModel, DocumentModel]:
        """Documento acotado a alguna de las filas de deudor del titular; 404 si ninguna
        lo tiene (no se confirma que exista)."""
        for debtor in debtors:
            row = await self._repo.get_owned(debtor.id, document_id)
            if row is not None:
                return row
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado")

    async def _require_self_debtors(self, session: UserSession) -> list[DebtorModel]:
        """Resuelve las filas de deudor (una por empresa) detrás de la sesión SELF.
        El documento de identidad va cifrado en la tabla, así que la búsqueda es
        por hash."""
        require_verified_identity(session)
        document_type, document_number_hash = get_self_identity(session)
        try:
            doc_type = UserDocumentType(document_type)
        except ValueError as e:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Tipo de documento no reconocido"
            ) from e

        debtors = await self._debtor_repo.list_by_document(
            doc_type, document_number_hash
        )
        if not debtors:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "No encontramos obligaciones a tu nombre"
            )
        return debtors

    # ── Mapeo a schema ───────────────────────────────────────────────────────

    @staticmethod
    def to_response(
        link: DebtorDocumentModel, document: DocumentModel
    ) -> DebtorDocumentResponse:
        return DebtorDocumentResponse(
            id=document.id,
            category=link.category,
            original_name=document.original_name,
            content_type=document.content_type,
            size_bytes=document.size_bytes,
            checksum=document.checksum,
            created_at=document.created_at,
        )

    @classmethod
    def to_list_response(
        cls, rows: Sequence[tuple[DebtorDocumentModel, DocumentModel]]
    ) -> DebtorDocumentListResponse:
        items = [cls.to_response(link, document) for link, document in rows]
        return DebtorDocumentListResponse(items=items, total=len(items))
