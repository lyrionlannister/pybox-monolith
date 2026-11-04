"""Orquesta el flujo de onboarding: OTP, datos personales/de empresa y documentos."""

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import DocumentScope
from app_platform.countries.repository.country_repository import CountryRepository
from app_platform.countries.services.country_service import CountryService
from app_platform.documents.enums.document_enums import MAX_DOCUMENT_SIZE_BYTES
from app_platform.documents.services.document_service import DocumentService
from app_platform.documents.utils.document_naming import (
    generate_uuid7_filename,
    resolve_content_type,
)
from app_platform.support.services.support_service import SupportService
from core.config.logger import logger
from core.config.redis_config import RedisConfig
from core.database.redis import redis_client
from core.security.services.encrypt_service import encrypt_service
from core.security.services.password_hasher_service import PasswordHasherService
from identity.auth.enums.auth_enums import AuthProvider
from identity.auth.enums.notification_enums import VerificationChannel
from identity.auth.factories import get_verification_service
from identity.onboarding.schemas.onboarding_schemas import (
    OnboardingRepMode,
    OnboardingStatusSchema,
    OrganizationOnboardingSchema,
    SetOnboardingPasswordSchema,
    SetPhoneSchema,
    UpdateProfileSchema,
)
from identity.organizations.enums.organization_enums import VerificationStatus
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
from identity.users.enums.user_enums import (
    IdentityVerificationStatus,
    UserRole,
    UserScope,
)
from identity.users.models.role_assignment_model import RoleAssignmentModel
from identity.users.models.user_model import UserModel
from identity.users.repository.role_assignment_repository import (
    RoleAssignmentRepository,
)
from identity.users.repository.user_repository import UserRepository
from identity.users.schemas.user_session_schema import mfa_verified_key
from identity.users.services.user_service import UserService
from receivables.contact_methods.enums.contact_method_enums import ContactMethodType
from receivables.contact_methods.services.self_service_contact_service import (
    SelfServiceContactService,
)


class OnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        user_repo: UserRepository,
        org_repo: OrganizationRepository,
        membership_repo: OrganizationMembershipRepository,
        role_repo: RoleAssignmentRepository,
        user_service: UserService,
        support_service: SupportService,
        self_service_contact_service: SelfServiceContactService,
    ) -> None:
        self._session = session
        self._country_repo = CountryRepository(session)
        self._country_service = CountryService(self._country_repo)
        self._document_service = DocumentService(session)
        self._user_repo = user_repo
        self._org_repo = org_repo
        self._membership_repo = membership_repo
        self._role_repo = role_repo
        self._user_service = user_service
        self._support_service = support_service
        self._self_service_contact_service = self_service_contact_service

    async def get_status(
        self,
        user_id: uuid.UUID,
        scope: UserScope,
        org: OrganizationModel | None = None,
    ) -> OnboardingStatusSchema:
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )

        email_verified = bool(user.is_email_verified)
        phone_set = bool(user.phone_number)
        phone_verified = bool(user.is_phone_verified)
        document_complete = bool(user.document_type and user.document_number)
        must_change_pw = bool(user.must_change_password)

        missing: list[str] = []
        if not email_verified:
            missing.append("email_verification")
        if not phone_set:
            missing.append("phone_set")
        if not phone_verified:
            missing.append("phone_verification")
        if not document_complete:
            missing.append("profile_document")
        if must_change_pw:
            missing.append("set_password")

        org_complete: bool | None = None
        if scope == UserScope.ORGANIZATION:
            org_complete = (
                org is not None
                and bool(org.country)
                and bool(org.fiscal_document_number)
                and bool(org.fiscal_document_id)
                and bool(org.mercantile_document_id)
            )
            if not org_complete:
                missing.append("organization_data")

        # Solo bloquea el onboarding SUBIR el documento (NOT_SUBMITTED), no que ya lo
        # haya aprobado/denegado Atención al Cliente: eso puede tardar días y no debería
        # dejar al titular sin poder usar el resto de la app mientras tanto — solo gatea
        # /credits/my-credits, /statements/my-statements y /judicial-notifications/mine
        # (ver requerir_identidad_verificada en esos services).
        identity_status = (
            user.identity_verification_status if scope == UserScope.SELF else None
        )
        if (
            scope == UserScope.SELF
            and identity_status == IdentityVerificationStatus.NOT_SUBMITTED
        ):
            missing.append("identity_verification")

        base_complete = (
            email_verified
            and phone_set
            and phone_verified
            and document_complete
            and not must_change_pw
        )
        if scope == UserScope.SELF:
            is_complete = (
                base_complete
                and identity_status != IdentityVerificationStatus.NOT_SUBMITTED
            )
        elif scope == UserScope.GLOBAL:
            is_complete = base_complete
        else:
            is_complete = base_complete and bool(org_complete)

        return OnboardingStatusSchema(
            email_verified=email_verified,
            phone_set=phone_set,
            phone_verified=phone_verified,
            document_complete=document_complete,
            org_complete=org_complete,
            identity_verification_status=identity_status,
            must_change_password=must_change_pw,
            is_complete=is_complete,
            missing_steps=missing,
        )

    async def request_otp(
        self, user_id: uuid.UUID, channel: VerificationChannel
    ) -> None:
        logger.info(
            "[onboarding_service] request_otp | user_id=%s channel=%s",
            user_id,
            channel.value,
        )
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            logger.warning(
                "[onboarding_service] request_otp_user_missing | user_id=%s", user_id
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )
        service = get_verification_service(channel, self._session)
        await service.send_code(user)
        logger.info(
            "[onboarding_service] request_otp_sent | user_id=%s channel=%s",
            user_id,
            channel.value,
        )

    async def verify_otp(
        self, user_id: uuid.UUID, channel: VerificationChannel, code: str
    ) -> None:
        logger.info(
            "[onboarding_service] verify_otp | user_id=%s channel=%s",
            user_id,
            channel.value,
        )
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            logger.warning(
                "[onboarding_service] verify_otp_user_missing | user_id=%s", user_id
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )
        service = get_verification_service(channel, self._session)
        await service.verify_code(user_id, code)

        if channel == VerificationChannel.EMAIL:
            user.is_email_verified = True
        else:
            user.is_phone_verified = True

        await self._user_repo.update(user)
        await self._propagate_verified_contact(user, channel)
        # Este mismo endpoint resuelve tanto la verificación de contacto del onboarding
        # como el desafío de MFA post-onboarding (ver MfaGuard en el frontend): un
        # código correcto siempre cuenta como "segundo factor superado" para el login
        # vigente (lo exige `_require_mfa_verified` en core/security/dependencies.py).
        await redis_client.set(mfa_verified_key(user_id), "1", RedisConfig.DEFAULT_TTL)
        logger.info(
            "[onboarding_service] verify_otp_done | user_id=%s channel=%s",
            user_id,
            channel.value,
        )

    async def _propagate_verified_contact(
        self, user: UserModel, channel: VerificationChannel
    ) -> None:
        """Guarda el correo/teléfono recién verificado como método de
        contacto del deudor.

        El deudor se ubica por (tipo, número de documento). Un fallo aquí no debe tumbar
        la verificación OTP, así que se aísla en un savepoint (begin_nested): si la
        propagación falla y envenena la transacción, solo se revierte el savepoint, no
        el OTP ya persistido.
        """
        if not user.document_type or not user.document_number_hash:
            return
        if channel == VerificationChannel.EMAIL:
            contact_type = ContactMethodType.EMAIL
            value = user.email
        else:
            contact_type = ContactMethodType.PHONE
            value = user.phone_number
        try:
            async with self._session.begin_nested():
                await self._self_service_contact_service.register_verified_contact(
                    document_type=user.document_type,
                    document_number_hash=user.document_number_hash,
                    contact_type=contact_type,
                    contact_value=value,
                    country_code=user.nationality,
                )
        except Exception:
            logger.warning(
                "[onboarding_service] propagate_contact_failed | user_id=%s channel=%s",
                user.id,
                channel.value,
                exc_info=True,
            )

    async def set_phone(self, user_id: uuid.UUID, data: SetPhoneSchema) -> None:
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )
        existing = await self._user_repo.get_by_phone_number(data.phone_number)
        if existing and existing.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El número de teléfono ya está registrado.",
            )
        user.phone_number = data.phone_number
        user.is_phone_verified = False
        await self._user_repo.update(user)

    async def update_profile(
        self, user_id: uuid.UUID, data: UpdateProfileSchema
    ) -> None:
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )
        # Validación contra DB (paises / paises_tipos_documento) en vez de enum
        # estático.
        nationality = await self._country_service.require_valid_country(
            data.nationality
        )
        await self._country_service.require_valid_document(
            data.document_type,
            DocumentScope.PERSON,
            country_code=nationality,
            required=True,
        )
        await self._user_service.apply_document_change(
            user, data.document_type, data.document_number or "", by_self=True
        )
        user.nationality = data.nationality
        await self._user_repo.update(user)
        await self._user_service.get_user_session(user_id)

    async def submit_identity_document(
        self, user_id: uuid.UUID, file: UploadFile
    ) -> IdentityVerificationStatus:
        """Sube el documento de identidad de un titular (PDF o foto) y abre el ticket
        de validación (Atención al Cliente GLOBAL). No hay nada que revertir si el
        ticket falla después de subir el archivo: `create_identity_verification_ticket`
        hace ambas cosas (adjunto + ticket) en una sola operación de SupportService."""
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )
        # DENIED sí puede reintentar (documento equivocado/ilegible la primera vez);
        # PENDING/APPROVED no: ya hay un ticket en curso o ya quedó aprobado.
        if user.identity_verification_status in (
            IdentityVerificationStatus.PENDING,
            IdentityVerificationStatus.APPROVED,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya enviaste tu documento de identidad.",
            )

        await self._support_service.create_identity_verification_ticket(
            user_id, user.full_name, file
        )

        user.identity_verification_status = IdentityVerificationStatus.PENDING
        await self._user_repo.update(user)
        await self._user_service.get_user_session(user_id)
        return user.identity_verification_status

    async def create_first_org(
        self,
        user_id: uuid.UUID,
        data: OrganizationOnboardingSchema,
        fiscal_file: UploadFile,
        mercantile_file: UploadFile,
        representative_file: UploadFile,
    ) -> OrganizationModel:
        # Validación contra DB antes de crear la org / subir archivos (falla rápido).
        country = await self._country_service.require_valid_country(data.country)
        if data.representative_mode == OnboardingRepMode.CREATE:
            await self._country_service.require_valid_document(
                data.rep_document_type, DocumentScope.PERSON, country_code=country
            )

        org = await self._org_repo.add(
            OrganizationModel(
                name=data.name,
                sector=data.sector,
                verification_status=VerificationStatus.PENDING,
            )
        )

        # Casos 1:1: cada documento lo apunta su propia columna de `entidades`
        # (id_documento_fiscal / mercantil / representante), así que no hay categoría ni
        # tabla de unión — la columna que lo referencia ya dice qué es.
        fiscal_doc = await self._store_org_upload(
            fiscal_file, org.id, "fiscal", user_id
        )
        mercantile_doc = await self._store_org_upload(
            mercantile_file, org.id, "mercantile", user_id
        )
        representative_doc = await self._store_org_upload(
            representative_file, org.id, "representative", user_id
        )

        org.country = data.country
        org.fiscal_document_type = await self._country_repo.get_document_code(
            data.country, DocumentScope.ORG_FISCAL
        )
        org.fiscal_document_number = (
            encrypt_service.encrypt_to_str(data.fiscal_document_number)
            if data.fiscal_document_number
            else None
        )
        org.fiscal_document_id = fiscal_doc.id
        org.mercantile_document_type = await self._country_repo.get_document_code(
            data.country, DocumentScope.ORG_MERCANTILE
        )
        org.mercantile_document_id = mercantile_doc.id
        org.representative_document_id = representative_doc.id
        updated_org = await self._org_repo.update(org)

        if data.representative_mode == OnboardingRepMode.SELF:
            await self._membership_repo.add(
                OrganizationMembershipModel(
                    user_id=user_id,
                    organization_id=updated_org.id,
                    created_by=user_id,
                    is_legal_representative=True,
                )
            )
        else:
            await self._membership_repo.add(
                OrganizationMembershipModel(
                    user_id=user_id,
                    organization_id=updated_org.id,
                    created_by=user_id,
                )
            )
            hasher = PasswordHasherService()
            hashed_pw = (
                hasher.hash_password(data.rep_password) if data.rep_password else None
            )
            rep_user = await self._user_repo.add(
                UserModel(
                    firstname=data.rep_firstname,
                    lastname=data.rep_lastname,
                    email=data.rep_email,
                    hashed_password=hashed_pw,
                    must_change_password=hashed_pw is not None,
                    auth_provider=AuthProvider.SELF,
                    document_type=data.rep_document_type,
                    document_number=(
                        encrypt_service.encrypt_to_str(data.rep_document_number)
                        if data.rep_document_number
                        else None
                    ),
                    document_number_hash=(
                        encrypt_service.hash_document(data.rep_document_number)
                        if data.rep_document_number
                        else None
                    ),
                )
            )
            await self._membership_repo.add(
                OrganizationMembershipModel(
                    user_id=rep_user.id,
                    organization_id=updated_org.id,
                    created_by=user_id,
                    is_legal_representative=True,
                )
            )
            await self._role_repo.add(
                RoleAssignmentModel(
                    user_id=rep_user.id,
                    role=UserRole.ADMIN,
                    scope=UserScope.ORGANIZATION,
                    organization_id=updated_org.id,
                )
            )

        pending_role = await self._role_repo.get_pending_org_admin(user_id)
        if pending_role is not None:
            pending_role.organization_id = updated_org.id
            await self._role_repo.update(pending_role)

        await self._support_service.create_org_verification_ticket(
            updated_org.id, user_id
        )
        await self._user_service.get_user_session(user_id)

        return updated_org

    async def _store_org_upload(
        self,
        file: UploadFile,
        org_id: uuid.UUID,
        label: str,
        user_id: uuid.UUID,
    ):
        content = await file.read()
        if len(content) > MAX_DOCUMENT_SIZE_BYTES:
            limit_mb = MAX_DOCUMENT_SIZE_BYTES // (1024 * 1024)
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"El archivo '{label}' supera el límite de {limit_mb} MB",
            )
        filename = generate_uuid7_filename(file.filename)
        return await self._document_service.store_generated(
            content=content,
            filename=filename,
            content_type=resolve_content_type(filename),
            domain=ORGANIZATION_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(org_id),
            uploaded_by=user_id,
            organization_id=org_id,
        )

    async def set_onboarding_password(
        self, user_id: uuid.UUID, data: SetOnboardingPasswordSchema
    ) -> None:
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )
        hasher = PasswordHasherService()
        user.hashed_password = hasher.hash_password(data.new_password)
        user.must_change_password = False
        await self._user_repo.update(user)
        await self._user_service.get_user_session(user_id)
