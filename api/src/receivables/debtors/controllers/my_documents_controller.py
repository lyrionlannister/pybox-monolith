"""Endpoint de autogestión: un deudor sube y consulta sus propios documentos."""

import uuid
from typing import Annotated, Optional

from fastapi import File, Form, Query, Response, UploadFile, status

from app_platform.documents.schemas.document_schemas import DocumentCategoryOption
from core.config.api_router import APIRouter
from core.security.dependencies import CurrentSession
from receivables.debtors.dependencies import DebtorDocumentServiceDep, RequireSelf
from receivables.debtors.enums.debtor_document_enums import DebtorDocumentCategory
from receivables.debtors.schemas.debtor_document_schemas import (
    DebtorDocumentListResponse,
    DebtorDocumentResponse,
)

# Vive en el dominio dueño del recurso: el documento cuelga de un deudor
# (`documentos_deudor`), no de una tabla polimórfica genérica.
router = APIRouter(prefix="/debtors/me/documents", tags=["Documentos del titular"])


@router.get(
    "/categories",
    response_model=list[DocumentCategoryOption],
    summary="Listar categorías de documento del titular",
    description=(
        "Catálogo código→etiqueta de las categorías del ámbito deudor, para los "
        "selects del front. Declarado antes de las rutas con {document_id} para "
        "que no se resuelva como un UUID."
    ),
)
async def list_categories(
    _: CurrentSession,
    service: DebtorDocumentServiceDep,
) -> list[DocumentCategoryOption]:
    return service.list_categories()


@router.get(
    "",
    response_model=DebtorDocumentListResponse,
    summary="Repositorio de documentos del titular",
    description="Documentos del titular autenticado, del más reciente al más antiguo. "
    "Opcionalmente filtrados por categoría.",
)
async def list_my_documents(
    session: RequireSelf,
    service: DebtorDocumentServiceDep,
    category: Annotated[Optional[DebtorDocumentCategory], Query()] = None,
) -> DebtorDocumentListResponse:
    return await service.list_mine(session, category)


@router.post(
    "",
    response_model=DebtorDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir un documento al repositorio del titular",
    description=(
        "El titular sube un documento propio (PDF, PNG, JPG o WebP, hasta 10 "
        "MB). Solo se aceptan las categorías que el titular puede aportar."
    ),
)
async def upload_my_document(
    session: RequireSelf,
    service: DebtorDocumentServiceDep,
    file: Annotated[UploadFile, File(description="Archivo a subir")],
    category: Annotated[
        DebtorDocumentCategory, Form(description="Categoría del documento")
    ],
) -> DebtorDocumentResponse:
    return await service.upload_mine(session, file, category)


@router.get(
    "/{document_id}/content",
    summary="Descargar un documento del titular",
    description=(
        "Trae el archivo del almacén por la red privada y lo entrega. El "
        "documento se resuelve contra el deudor de la sesión: si no es suyo "
        "responde 404."
    ),
    response_class=Response,
)
async def download_my_document(
    document_id: uuid.UUID,
    session: RequireSelf,
    service: DebtorDocumentServiceDep,
) -> Response:
    return await service.get_mine_content(session, document_id)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un documento del titular",
    description=(
        "Baja lógica: se marca eliminado el enlace y la fila de metadatos. Los "
        "bytes los borra después el proceso de purga, así que un admin global "
        "puede restaurarlo."
    ),
)
async def delete_my_document(
    document_id: uuid.UUID,
    session: RequireSelf,
    service: DebtorDocumentServiceDep,
) -> None:
    await service.delete_mine(session, document_id)
