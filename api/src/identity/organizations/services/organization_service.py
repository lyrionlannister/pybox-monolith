"""Alta, edición y verificación de organizaciones, y sus documentos legales."""

import uuid
from datetime import datetime
from typing import Sequence

from fastapi import HTTPException, status

from app_platform.countries.enums.country_enums import DocumentScope
from app_platform.countries.repository.country_repository import CountryRepository
from app_platform.countries.services.country_service import CountryService
from app_platform.documents.repository.document_repository import DocumentRepository
from app_platform.documents.services.document_service import DocumentService
from app_platform.documents.utils.document_naming import resolve_content_type
from core.config.logger import logger
from core.database.redis import redis_client
from core.security.policies.security_policies import (
    require_org_access,
    require_verified_org,
)
from core.security.services.encrypt_service import encrypt_service
from identity.organizations.enums.organization_enums import (
    ENTITY_SECTOR_LABELS,
    EntitySectors,
)
from identity.organizations.models.organization_membership_model import (
    OrganizationMembershipModel,
)
from identity.organizations.models.organization_model import OrganizationModel
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.organizations.repository.organization_repository import (
    ORGANIZATION_DOCUMENT_STORAGE_DOMAIN,
    OrganizationRepository,
)
from identity.organizations.schemas.organization_schemas import (
    EntitySectorOption,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
    OrgRegisterResponse,
    RepresentativeMode,
)
from identity.organizations.services.organization_cascade_service import (
    OrganizationCascadeService,
)
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.models.role_assignment_model import RoleAssignmentModel
from identity.users.models.user_model import UserModel
from identity.users.repository.permission_assignment_repository import (
    PermissionAssignmentRepository,
)
from identity.users.repository.role_assignment_repository import (
    RoleAssignmentRepository,
)
from identity.users.repository.user_repository import UserRepository
from identity.users.schemas.user_session_schema import UserSession, session_key
from messaging.campaigns.repository.campaign_repository import CampaignRepository
from messaging.contacts.repository.contact_repository import ContactRepository
from receivables.credits.repository.credit_repository import CreditRepository

# pylint: disable-next=line-too-long
from receivables.portfolios.repository.portfolio_daily_counter_config_repository import (
    PortfolioDailyCounterConfigRepository,
)
from receivables.portfolios.repository.portfolio_repository import PortfolioRepository
from receivables.portfolios.repository.portfolio_user_access_repository import (
    PortfolioUserAccessRepository,
)
from receivables.portfolios.services.portfolio_service import PortfolioService


class OrganizationService:
    def __init__(
        self,
        org_repo: OrganizationRepository,
        membership_repo: OrganizationMembershipRepository,
        role_assignment_repo: RoleAssignmentRepository,
        user_repo: UserRepository | None = None,
    ):
        self.org_repo = org_repo
        self.membership_repo = membership_repo
        self.role_assignment_repo = role_assignment_repo
        self.user_repo = user_repo
        self._country_repo = CountryRepository(org_repo.session)
        self._country_service = CountryService(self._country_repo)
        self._document_service = DocumentService(org_repo.session)
        self._document_repo = DocumentRepository(org_repo.session)
        self._permission_assignment_repo = PermissionAssignmentRepository(
            org_repo.session
        )
        # Dar de baja una organización arrastra sus portafolios (y con ellos créditos y
        # campañas): esa cascada la conoce el dominio dueño de los portafolios.
        self._portfolio_service = PortfolioService(
            PortfolioRepository(org_repo.session),
            PortfolioDailyCounterConfigRepository(org_repo.session),
            CreditRepository(org_repo.session),
            CampaignRepository(org_repo.session),
            ContactRepository(org_repo.session),
            PortfolioUserAccessRepository(org_repo.session),
        )
        # ...y con ellos deudores, chats, IVR, reportes, documentos y accesos.
        self._cascade_service = OrganizationCascadeService(org_repo.session)

    # ── Queries ──────────────────────────────────────────────────────────────

    def list_sectors(self) -> list[EntitySectorOption]:
        """Catálogo de sectores para los selects del front. Se arma desde el enum, que
        es la fuente de verdad; el front no mantiene su propia copia de la lista."""
        return [
            EntitySectorOption(value=sector.value, label=ENTITY_SECTOR_LABELS[sector])
            for sector in EntitySectors
        ]

    async def get_all(self) -> Sequence[OrganizationModel]:
        return await self.org_repo.get_all()

    async def get_for_user(
        self, user_id: uuid.UUID, scope: UserScope
    ) -> Sequence[OrganizationModel]:
        if scope == UserScope.GLOBAL:
            return await self.org_repo.get_all()
        if scope == UserScope.ORGANIZATION:
            memberships = await self.membership_repo.get_by_user_id(user_id)
            org_ids = [m.organization_id for m in memberships]
            return await self.org_repo.get_by_ids(org_ids)
        return []

    async def get_by_id(self, org_id: uuid.UUID) -> OrganizationModel:
        org = await self.org_repo.get_by_id(org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organización no encontrada",
            )
        return org

    # ── Documentos de verificación de la entidad (casos 1:1) ─────────────────
    # Fiscal, mercantil y representante NO usan tabla de unión: cada uno lo apunta su
    # propia columna de `entidades` (`id_documento_fiscal` / `_mercantil` /
    # `_representante`), que además tiene FK compuesta contra
    # `(documentos.id, documentos.id_organizacion)` — Postgres ya rechaza que una
    # entidad apunte a un documento de otra. El único scope de tenant que necesita
    # la lectura es, por eso, `documentos.id_organizacion`.

    async def get_document_content(
        self, session: UserSession, org_id: uuid.UUID, document_id: uuid.UUID
    ):
        """Entrega el archivo de un documento de la entidad.

        Antes vivía en `DocumentService.get_organization_document`; se movió al
        dominio dueño del recurso. La autorización no cambió: gate de acceso a la
        organización (política pura) + filtro por organización en el repo, y 404
        si el documento no es de esa entidad (no se confirma su existencia fuera
        del alcance).
        """
        require_org_access(session, str(org_id))
        document = await self._document_repo.get_by_organization(document_id, org_id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento no encontrado")
        return await self._document_service.to_content_response(
            document, session.user_id
        )

    async def replace_document(
        self,
        org: OrganizationModel,
        field_name: str,
        file_bytes: bytes,
        filename: str,
        uploaded_by: uuid.UUID,
    ) -> OrganizationModel:
        """Sustituye uno de los tres documentos de verificación.

        El anterior se da de baja al final y no antes: si la subida del nuevo falla, la
        entidad se queda con el que tenía en vez de sin ninguno.
        """
        document = await self._document_service.store_verified_upload(
            content=file_bytes,
            filename=filename,
            content_type=resolve_content_type(filename),
            domain=ORGANIZATION_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(org.id),
            uploaded_by=uploaded_by,
            organization_id=org.id,
        )
        previous_document_id = getattr(org, field_name)
        setattr(org, field_name, document.id)
        updated = await self.org_repo.update(org)

        if previous_document_id is not None and previous_document_id != document.id:
            await self._document_service.delete_by_id(previous_document_id)
        return updated

    async def ensure_verified(self, org_id: uuid.UUID) -> None:
        """Envuelve `get_by_id` + `require_verified_org`: los controllers de subida de
        portafolio/cuotas necesitaban esta misma pareja de llamadas antes de instanciar
        `OrganizationRepository` directo (saltándose esta capa de servicio)."""
        require_verified_org(await self.org_repo.get_by_id(org_id))

    # ── Construcción de respuesta HTTP ──────────────────────────────────────
    # El descifrado vive aquí, no en un `field_validator` del schema (ver
    # organization_schemas.py): los métodos de arriba devuelven el ORM tal cual
    # porque el controller también los usa para mutar y volver a guardar (p. ej.
    # `request_verification`), no solo para responder HTTP.

    def to_response(self, org: OrganizationModel) -> OrganizationResponse:
        return OrganizationResponse(
            id=org.id,
            name=org.name,
            sector=org.sector,
            description=org.description,
            country=org.country,
            fiscal_document_type=org.fiscal_document_type,
            fiscal_document_number=(
                encrypt_service.decrypt_to_str(org.fiscal_document_number)
                if org.fiscal_document_number
                else None
            ),
            fiscal_document_id=org.fiscal_document_id,
            mercantile_document_type=org.mercantile_document_type,
            mercantile_document_id=org.mercantile_document_id,
            representative_document_id=org.representative_document_id,
            logo_document_id=org.logo_document_id,
            verification_status=org.verification_status,
            created_at=org.created_at,
            updated_at=org.updated_at,
        )

    def to_register_response(self, org: OrganizationModel) -> OrgRegisterResponse:
        return OrgRegisterResponse(
            id=org.id,
            name=org.name,
            sector=org.sector,
            description=org.description,
            country=org.country,
            fiscal_document_type=org.fiscal_document_type,
            fiscal_document_number=(
                encrypt_service.decrypt_to_str(org.fiscal_document_number)
                if org.fiscal_document_number
                else None
            ),
            mercantile_document_type=org.mercantile_document_type,
            representative_document_id=org.representative_document_id,
            created_at=org.created_at,
        )

    # ── Ownership helper ─────────────────────────────────────────────────────

    async def assert_admin_of_org(self, user_id: uuid.UUID, org_id: uuid.UUID) -> None:
        admin_org_ids = await self.role_assignment_repo.get_admin_org_ids(user_id)
        if org_id not in admin_org_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para gestionar esta organización",
            )

    # ── Write operations ─────────────────────────────────────────────────────

    async def create_organization(
        self,
        data: OrganizationCreate,
        created_by_user_id: uuid.UUID,
        scope: UserScope,
    ) -> OrganizationModel:
        # Validación contra DB (paises / paises_tipos_documento) en vez de enum
        # estático.
        country = await self._country_service.require_valid_country(
            data.country, required=False
        )
        await self._country_service.require_valid_document(
            data.fiscal_document_type, DocumentScope.ORG_FISCAL, country_code=country
        )
        await self._country_service.require_valid_document(
            data.mercantile_document_type,
            DocumentScope.ORG_MERCANTILE,
            country_code=country,
        )
        org_data = data.model_dump()
        if org_data.get("fiscal_document_number"):
            org_data["fiscal_document_number"] = encrypt_service.encrypt_to_str(
                org_data["fiscal_document_number"]
            )
        org = OrganizationModel(**org_data)
        org = await self.org_repo.add(org)

        if scope == UserScope.ORGANIZATION:
            membership = OrganizationMembershipModel(
                user_id=created_by_user_id,
                organization_id=org.id,
                created_by=created_by_user_id,
            )
            await self.membership_repo.add(membership)

            pending = await self.role_assignment_repo.get_pending_org_admin(
                created_by_user_id
            )
            if pending:
                pending.organization_id = org.id
                await self.role_assignment_repo.update(pending)
            else:
                assignment = RoleAssignmentModel(
                    user_id=created_by_user_id,
                    role=UserRole.ADMIN,
                    scope=UserScope.ORGANIZATION,
                    organization_id=org.id,
                )
                await self.role_assignment_repo.add(assignment)

            await redis_client.delete(session_key(created_by_user_id))

        logger.info(
            "[org] create | org_id=%s user_id=%s scope=%s",
            org.id,
            created_by_user_id,
            scope.value,
        )
        return org

    async def _require_existing_admin_colleague(
        self, admin_user_id: uuid.UUID, candidate_user_id: uuid.UUID
    ) -> None:
        """`representative_mode=select` no puede nombrar representante legal a un
        tercero arbitrario: solo a alguien que ya comparte una organización con el
        admin que registra (donde ese admin administra), evitando que se le asigne
        `is_legal_representative=True` a un usuario sin su conocimiento."""
        admin_memberships = await self.membership_repo.get_by_user_id(admin_user_id)
        admin_org_ids = {
            m.organization_id for m in admin_memberships if m.role == UserRole.ADMIN
        }
        if not admin_org_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Debes seleccionar un representante legal que ya pertenezca a "
                    "una organización que administras."
                ),
            )
        candidate_memberships = await self.membership_repo.get_by_user_id(
            candidate_user_id
        )
        candidate_org_ids = {m.organization_id for m in candidate_memberships}
        if not candidate_org_ids & admin_org_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Debes seleccionar un representante legal que ya pertenezca a "
                    "una organización que administras."
                ),
            )

    async def register_with_representative(
        self,
        name: str,
        sector: EntitySectors,
        description: str | None,
        country: str,
        fiscal_document_number: str | None,
        representative_mode: RepresentativeMode,
        representative_user_id: uuid.UUID | None,
        rep_firstname: str | None,
        rep_lastname: str | None,
        rep_email: str | None,
        rep_document_type: str | None,
        rep_document_number: str | None,
        fiscal_file_bytes: bytes,
        fiscal_filename: str,
        mercantile_file_bytes: bytes,
        mercantile_filename: str,
        representative_file_bytes: bytes,
        representative_filename: str,
        created_by_user_id: uuid.UUID,
        scope: UserScope,
        admin_scope: UserScope,
    ) -> OrganizationModel:
        if self.user_repo is None:
            raise RuntimeError("user_repo is required for register_with_representative")

        # Validación de país contra DB (falla rápido antes de crear usuario/subir
        # archivos).
        country = await self._country_service.require_valid_country(country)

        # 1. Resolve legal representative user_id
        rep_user_id: uuid.UUID
        if representative_mode == RepresentativeMode.SELF:
            rep_user_id = created_by_user_id
        elif representative_mode == RepresentativeMode.SELECT:
            if not representative_user_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Debes seleccionar un representante legal.",
                )
            if admin_scope != UserScope.GLOBAL:
                await self._require_existing_admin_colleague(
                    created_by_user_id, representative_user_id
                )
            rep_user_id = representative_user_id
        else:  # CREATE
            for field, label in [
                (rep_firstname, "nombre"),
                (rep_lastname, "apellido"),
                (rep_email, "correo"),
                (rep_document_type, "tipo de documento"),
                (rep_document_number, "número de documento"),
            ]:
                if not field:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"El campo '{label}' es obligatorio para crear un "
                            "representante."
                        ),
                    )
            existing = await self.user_repo.get_by_email(  # type: ignore[arg-type]
                rep_email
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ya existe un usuario con ese correo electrónico.",
                )
            await self._country_service.require_valid_document(
                rep_document_type,
                DocumentScope.PERSON,
                country_code=country,
                required=True,
            )
            rep_doc_hash = (
                encrypt_service.hash_document(rep_document_number)
                if rep_document_number
                else None
            )
            new_user = UserModel(
                firstname=rep_firstname,
                lastname=rep_lastname,
                email=rep_email,
                document_type=rep_document_type,
                document_number=(
                    encrypt_service.encrypt_to_str(rep_document_number)
                    if rep_document_number
                    else None
                ),
                document_number_hash=rep_doc_hash,
            )
            new_user = await self.user_repo.add(new_user)
            rep_user_id = new_user.id  # type: ignore[assignment]

        # 2. Resolve doc types from country (desde DB)
        fiscal_doc_type = await self._country_repo.get_document_code(
            country, DocumentScope.ORG_FISCAL
        )
        mercantile_doc_type = await self._country_repo.get_document_code(
            country, DocumentScope.ORG_MERCANTILE
        )

        # 3. Create organization (sin documentos todavía: hacen falta el id para el FK
        # `organization_id` de cada fila `documentos`).
        org = OrganizationModel(
            name=name,
            sector=sector,
            description=description,
            country=country,
            fiscal_document_type=fiscal_doc_type,
            fiscal_document_number=(
                encrypt_service.encrypt_to_str(fiscal_document_number)
                if fiscal_document_number
                else None
            ),
            mercantile_document_type=mercantile_doc_type,
        )
        org = await self.org_repo.add(org)

        # 4. Subir los 3 documentos al almacén de objetos, ya con el id de la
        # organización. El nombre real del archivo subido se conserva como
        # `original_name` (para mostrar y descargar); la clave del objeto en el
        # almacén siempre es un UUID (build_object_key), nunca este nombre.
        rep_filename = representative_filename

        fiscal_doc = await self._document_service.store_verified_upload(
            content=fiscal_file_bytes,
            filename=fiscal_filename,
            content_type=resolve_content_type(fiscal_filename),
            domain=ORGANIZATION_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(org.id),
            uploaded_by=created_by_user_id,
            organization_id=org.id,
        )
        mercantile_doc = await self._document_service.store_verified_upload(
            content=mercantile_file_bytes,
            filename=mercantile_filename,
            content_type=resolve_content_type(mercantile_filename),
            domain=ORGANIZATION_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(org.id),
            uploaded_by=created_by_user_id,
            organization_id=org.id,
        )
        rep_doc = await self._document_service.store_verified_upload(
            content=representative_file_bytes,
            filename=rep_filename,
            content_type=resolve_content_type(rep_filename),
            domain=ORGANIZATION_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(org.id),
            uploaded_by=created_by_user_id,
            organization_id=org.id,
        )

        org.fiscal_document_id = fiscal_doc.id
        org.mercantile_document_id = mercantile_doc.id
        org.representative_document_id = rep_doc.id
        org = await self.org_repo.update(org)
        logger.info(
            "[org] register_with_rep | org_id=%s mode=%s user_id=%s",
            org.id,
            representative_mode.value,
            created_by_user_id,
        )

        # 6. Membership for legal representative (always with flag)
        rep_membership = OrganizationMembershipModel(
            user_id=rep_user_id,
            organization_id=org.id,
            created_by=created_by_user_id,
            is_legal_representative=True,
        )
        await self.membership_repo.add(rep_membership)

        # 7. Membership + role for the creating user (if different from rep)
        if created_by_user_id != rep_user_id:
            creator_membership = OrganizationMembershipModel(
                user_id=created_by_user_id,
                organization_id=org.id,
                created_by=created_by_user_id,
            )
            await self.membership_repo.add(creator_membership)

        # 8. Role assignment for creator
        if scope == UserScope.ORGANIZATION:
            pending = await self.role_assignment_repo.get_pending_org_admin(
                created_by_user_id
            )
            if pending:
                pending.organization_id = org.id
                await self.role_assignment_repo.update(pending)
            else:
                await self.role_assignment_repo.add(
                    RoleAssignmentModel(
                        user_id=created_by_user_id,
                        role=UserRole.ADMIN,
                        scope=UserScope.ORGANIZATION,
                        organization_id=org.id,
                    )
                )

            await redis_client.delete(session_key(created_by_user_id))

        return org

    async def update_organization(
        self,
        org_id: uuid.UUID,
        data: OrganizationUpdate,
        requesting_user_id: uuid.UUID,
        scope: UserScope,
    ) -> OrganizationModel:
        if scope == UserScope.ORGANIZATION:
            await self.assert_admin_of_org(requesting_user_id, org_id)

        org = await self.get_by_id(org_id)

        for field, value in data.model_dump(exclude_unset=True).items():
            if field == "fiscal_document_number" and value is not None:
                value = encrypt_service.encrypt_to_str(value)
            setattr(org, field, value)

        updated = await self.org_repo.update(org)
        logger.info("[org] update | org_id=%s user_id=%s", org_id, requesting_user_id)
        return updated

    async def delete_organization(
        self,
        org_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        scope: UserScope,
    ) -> None:
        if scope == UserScope.ORGANIZATION:
            await self.assert_admin_of_org(requesting_user_id, org_id)

        await self.get_by_id(org_id)  # raises 404 if not found
        await self.soft_delete_organization(org_id)
        logger.info("[org] delete | org_id=%s user_id=%s", org_id, requesting_user_id)

    # ── Soft-delete cascade (also called from UserService) ───────────────────

    async def soft_delete_organization(self, org_id: uuid.UUID) -> None:
        """Baja lógica de la organización y, en cascada, de todo lo que le pertenece:
        membresías, roles y permisos de sus usuarios, portafolios (con sus créditos y
        campañas), deudores (con sus contactos, direcciones y documentos), extractos,
        notificaciones judiciales, chats y credenciales de WhatsApp, IVR,
        resultados de campañas, reportes, documentos y accesos a portafolios.
        Facturas y tickets de soporte no se tocan.

        Los usuarios NO se eliminan: quedan sin organización (los que no tengan otra
        vuelven a la sesión sin roles, la del titular). Toda la cascada lleva el mismo
        `deleted_at` que la organización para que `restore_organization` revierta solo
        lo que cayó con ella, no lo que ya estaba dado de baja antes.
        """
        org = await self.org_repo.get_by_id(org_id)
        if org is None:
            return

        deleted = await self.org_repo.delete(org)
        deleted_at = deleted.deleted_at
        assert deleted_at is not None

        user_ids = await self.membership_repo.soft_delete_by_organization(
            org_id, deleted_at
        )
        await self.role_assignment_repo.soft_delete_by_organization(org_id, deleted_at)
        await self._permission_assignment_repo.soft_delete_by_organization(
            org_id, deleted_at
        )
        await self._portfolio_service.delete_for_organization(org_id, deleted_at)
        await self._cascade_service.soft_delete_for_organization(org_id, deleted_at)
        await self._invalidate_sessions(user_ids)

    async def restore_organization(self, org_id: uuid.UUID) -> OrganizationModel | None:
        org = await self.org_repo.get_by_id_including_deleted(org_id)
        if org is None or org.deleted_at is None:
            return org

        deleted_at: datetime = org.deleted_at
        await self.org_repo.restore(org)

        user_ids = await self.membership_repo.restore_by_organization(
            org_id, deleted_at
        )
        await self.role_assignment_repo.restore_by_organization(org_id, deleted_at)
        await self._permission_assignment_repo.restore_by_organization(
            org_id, deleted_at
        )
        await self._portfolio_service.restore_for_organization(org_id, deleted_at)
        await self._cascade_service.restore_for_organization(org_id, deleted_at)
        await self._invalidate_sessions(user_ids)

        return org

    @staticmethod
    async def _invalidate_sessions(user_ids: list[uuid.UUID]) -> None:
        """La sesión cacheada en Redis lista las organizaciones del usuario: sin esto
        seguiría viendo (o sin ver) la organización hasta que expire."""
        for user_id in user_ids:
            await redis_client.delete(session_key(user_id))
