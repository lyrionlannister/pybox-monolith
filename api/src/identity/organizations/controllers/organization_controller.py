"""Endpoints de organizaciones: alta, edición, verificación y documentos."""

import uuid
from typing import Literal

from fastapi import File, Form, HTTPException, Response, UploadFile, status

from app_platform.documents.utils.document_naming import (
    generate_uuid7_filename,
    resolve_content_type,
)
from app_platform.support.dependencies import SupportServiceDep
from core.config.api_router import APIRouter
from core.security.dependencies import CurrentSession, PendingMfaSession
from core.security.policies.security_policies import (
    require_global_admin,
    require_org_access,
)
from identity.onboarding.dependencies import CurrentScope
from identity.organizations.dependencies import AdminScopeDep, OrgServiceDep
from identity.organizations.enums.organization_enums import (
    EntitySectors,
    VerificationStatus,
)
from identity.organizations.schemas.organization_schemas import (
    EntitySectorOption,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
    OrgRegisterResponse,
    RepresentativeMode,
)
from identity.organizations.utils.document_upload_utils import require_within_size_limit
from identity.users.dependencies import UserServiceDep
from identity.users.enums.user_enums import UserScope

_ORG_DOCUMENT_FIELD: dict[str, str] = {
    "fiscal": "fiscal_document_id",
    "mercantil": "mercantile_document_id",
    "representante": "representative_document_id",
    "logo": "logo_document_id",
}

router = APIRouter(prefix="/organizations", tags=["Organizaciones"])


@router.get(
    "/",
    response_model=list[OrganizationResponse],
    summary="Listar organizaciones del usuario",
)
async def list_organizations(
    session: CurrentSession,
    scope: CurrentScope,
    service: OrgServiceDep,
) -> list[OrganizationResponse]:
    orgs = await service.get_for_user(session.user_id, scope)
    return [service.to_response(org) for org in orgs]


@router.get(
    "/sectors",
    response_model=list[EntitySectorOption],
    summary="Listar sectores de entidad",
    description=(
        "Catálogo código→etiqueta de sectores, para los selects del front. Debe "
        "quedar declarado antes de /{org_id} para que la ruta no se resuelva como "
        "un UUID. Usa PendingMfaSession porque el wizard de onboarding (paso "
        "'organization', antes de POST /onboarding/organization) lo consume "
        "mientras el MFA todavía puede estar pendiente."
    ),
)
async def list_sectors(
    _: PendingMfaSession,
    service: OrgServiceDep,
) -> list[EntitySectorOption]:
    return service.list_sectors()


@router.get(
    "/{org_id}",
    response_model=OrganizationResponse,
    summary="Obtener organización por ID",
)
async def get_organization(
    org_id: uuid.UUID,
    session: CurrentSession,
    service: OrgServiceDep,
) -> OrganizationResponse:
    require_org_access(session, str(org_id))
    org = await service.get_by_id(org_id)
    return service.to_response(org)


@router.post(
    "/",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear organización",
)
async def create_organization(
    body: OrganizationCreate,
    session: CurrentSession,
    admin_scope: AdminScopeDep,
    service: OrgServiceDep,
    user_service: UserServiceDep,
) -> OrganizationResponse:
    org = await service.create_organization(body, session.user_id, admin_scope)
    await user_service.get_user_session(session.user_id)
    return service.to_response(org)


@router.patch(
    "/{org_id}",
    response_model=OrganizationResponse,
    summary="Actualizar datos de la organización",
)
async def update_organization(
    org_id: uuid.UUID,
    body: OrganizationUpdate,
    session: CurrentSession,
    admin_scope: AdminScopeDep,
    service: OrgServiceDep,
) -> OrganizationResponse:
    updated = await service.update_organization(
        org_id, body, session.user_id, admin_scope
    )
    return service.to_response(updated)


@router.post(
    "/{org_id}/request-verification",
    response_model=OrganizationResponse,
    summary="Volver a solicitar verificación de la organización",
)
async def request_verification(
    org_id: uuid.UUID,
    session: CurrentSession,
    admin_scope: AdminScopeDep,
    service: OrgServiceDep,
    support_service: SupportServiceDep,
) -> OrganizationResponse:
    if admin_scope == UserScope.ORGANIZATION:
        await service.assert_admin_of_org(session.user_id, org_id)
    org = await service.get_by_id(org_id)
    org.verification_status = VerificationStatus.PENDING
    org = await service.org_repo.update(org)
    await support_service.create_org_verification_ticket(org_id, session.user_id)
    return service.to_response(org)


@router.patch(
    "/{org_id}/documents/{doc_type}",
    response_model=OrganizationResponse,
    summary="Actualizar documento de la organización",
)
async def update_org_document(
    org_id: uuid.UUID,
    doc_type: Literal["fiscal", "mercantil", "representante", "logo"],
    session: CurrentSession,
    admin_scope: AdminScopeDep,
    service: OrgServiceDep,
    file: UploadFile = File(...),
) -> OrganizationResponse:
    if admin_scope == UserScope.ORGANIZATION:
        await service.assert_admin_of_org(session.user_id, org_id)
    org = await service.get_by_id(org_id)
    file_bytes = await file.read()
    require_within_size_limit(file_bytes)

    if doc_type == "logo" and resolve_content_type(file.filename) == "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "El logo debe ser una imagen (PNG, JPG o WebP)",
        )

    updated = await service.replace_document(
        org=org,
        field_name=_ORG_DOCUMENT_FIELD[doc_type],
        file_bytes=file_bytes,
        filename=generate_uuid7_filename(file.filename),
        uploaded_by=session.user_id,
    )
    return service.to_response(updated)


@router.get(
    "/{org_id}/documents/{document_id}/content",
    summary="Descargar un documento de la organización",
    description=(
        "Autoriza a un usuario con acceso a la entidad dueña y entrega el "
        "archivo. Si el documento no es de esa organización responde 404. Antes "
        "vivía en `/documents/organizations/{org_id}/{document_id}/content`."
    ),
    response_class=Response,
)
async def download_org_document(
    org_id: uuid.UUID,
    document_id: uuid.UUID,
    session: CurrentSession,
    service: OrgServiceDep,
) -> Response:
    return await service.get_document_content(session, org_id, document_id)


@router.delete(
    "/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar organización",
)
async def delete_organization(
    org_id: uuid.UUID,
    session: CurrentSession,
    admin_scope: AdminScopeDep,
    service: OrgServiceDep,
) -> None:
    await service.delete_organization(org_id, session.user_id, admin_scope)


@router.post(
    "/{org_id}/restore",
    status_code=status.HTTP_200_OK,
    summary="Restaurar organización",
    description=(
        "Deshace la baja lógica de la organización y de sus membresías. Solo "
        "administradores globales — restaurar no es un poder de admin de "
        "organización."
    ),
)
async def restore_organization(
    org_id: uuid.UUID,
    session: CurrentSession,
    service: OrgServiceDep,
) -> None:
    require_global_admin(session)
    await service.restore_organization(org_id)


@router.post(
    "/register",
    response_model=OrgRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar organización con documentos",
    description=(
        "Crea una organización con sus documentos fiscales, mercantiles y del "
        "representante legal. Genera automáticamente un ticket de verificación."
    ),
)
async def register_organization(
    session: CurrentSession,
    admin_scope: AdminScopeDep,
    service: OrgServiceDep,
    user_service: UserServiceDep,
    support_service: SupportServiceDep,
    name: str = Form(...),
    sector: EntitySectors = Form(...),
    country: str = Form(...),
    fiscal_document_number: str | None = Form(None),
    description: str | None = Form(None),
    representative_mode: RepresentativeMode = Form(...),
    representative_user_id: uuid.UUID | None = Form(None),
    rep_firstname: str | None = Form(None),
    rep_lastname: str | None = Form(None),
    rep_email: str | None = Form(None),
    rep_document_type: str | None = Form(None),
    rep_document_number: str | None = Form(None),
    fiscal_document_file: UploadFile = File(...),
    mercantile_document_file: UploadFile = File(...),
    representative_document_file: UploadFile = File(...),
) -> OrgRegisterResponse:
    fiscal_bytes = await fiscal_document_file.read()
    require_within_size_limit(fiscal_bytes)
    fiscal_filename = generate_uuid7_filename(fiscal_document_file.filename)
    mercantile_bytes = await mercantile_document_file.read()
    require_within_size_limit(mercantile_bytes)
    mercantile_filename = generate_uuid7_filename(mercantile_document_file.filename)
    rep_bytes = await representative_document_file.read()
    require_within_size_limit(rep_bytes)
    rep_filename = generate_uuid7_filename(representative_document_file.filename)
    org = await service.register_with_representative(
        name=name,
        sector=sector,
        description=description,
        country=country,
        fiscal_document_number=fiscal_document_number,
        representative_mode=representative_mode,
        representative_user_id=representative_user_id,
        rep_firstname=rep_firstname,
        rep_lastname=rep_lastname,
        rep_email=rep_email,
        rep_document_type=rep_document_type,
        rep_document_number=rep_document_number,
        fiscal_file_bytes=fiscal_bytes,
        fiscal_filename=fiscal_filename,
        mercantile_file_bytes=mercantile_bytes,
        mercantile_filename=mercantile_filename,
        representative_file_bytes=rep_bytes,
        representative_filename=rep_filename,
        created_by_user_id=session.user_id,
        admin_scope=admin_scope,
        scope=admin_scope,
    )
    await support_service.create_org_verification_ticket(org.id, session.user_id)
    await user_service.get_user_session(session.user_id)
    return service.to_register_response(org)
