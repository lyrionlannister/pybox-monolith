"""Gestión de usuarios: alta, permisos, preferencias y disponibilidad para chat."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Response, UploadFile, status

from app_platform.chats.websocket.connection_manager import ws_manager
from app_platform.countries.enums.country_enums import DocumentScope
from app_platform.countries.repository.country_repository import CountryRepository
from app_platform.countries.services.country_service import CountryService
from app_platform.documents.services.document_service import DocumentService
from core.config.logger import logger
from core.database.redis import RedisClient, redis_client
from core.security.constants.permissions import ORG_USERS
from core.security.constants.role_permissions_catalog import get_base_permissions
from core.security.services.auth_token_service import AuthTokenService
from core.security.services.encrypt_service import encrypt_service
from identity.organizations.repository.organization_membership_repository import (
    OrganizationMembershipRepository,
)
from identity.organizations.repository.organization_repository import (
    OrganizationRepository,
)
from identity.organizations.services.organization_service import OrganizationService
from identity.users.constants.tour_keys import TOUR_KEYS
from identity.users.enums.user_enums import PermissionEffect, UserRole, UserScope
from identity.users.models.role_assignment_model import RoleAssignmentModel
from identity.users.models.user_model import UserModel
from identity.users.repository.permission_assignment_repository import (
    PermissionAssignmentRepository,
)
from identity.users.repository.role_assignment_repository import (
    RoleAssignmentRepository,
)
from identity.users.repository.user_preferences_repository import (
    UserPreferencesRepository,
)
from identity.users.repository.user_repository import (
    USER_DOCUMENT_STORAGE_DOMAIN,
    UserRepository,
)
from identity.users.schemas.user_schemas import (
    AdminUserDetailSchema,
    AdminUserSummarySchema,
    ChatAvailableUserSchema,
    ProfilePhotoSchema,
    RoleEntrySchema,
    UpdateUserSchema,
)
from identity.users.schemas.user_session_schema import (
    OrgSessionEntry,
    UserSession,
    mfa_verified_key,
    session_key,
)


class UserService:
    def __init__(
        self,
        user_repo: UserRepository,
        org_repo: OrganizationRepository,
        membership_repo: OrganizationMembershipRepository,
        role_assignment_repo: RoleAssignmentRepository,
        permission_assignment_repo: PermissionAssignmentRepository,
        preferences_repo: UserPreferencesRepository,
        redis: RedisClient | None = None,
    ):
        self.user_repo = user_repo
        self.org_repo = org_repo
        self.membership_repo = membership_repo
        self.role_assignment_repo = role_assignment_repo
        self.permission_assignment_repo = permission_assignment_repo
        self.preferences_repo = preferences_repo
        self._redis = redis
        self._country_service = CountryService(CountryRepository(user_repo.session))
        self._document_service = DocumentService(user_repo.session)

    @property
    def redis(self) -> RedisClient:
        if self._redis is None:
            self._redis = redis_client
        return self._redis

    async def get_user_session(self, user_id: uuid.UUID) -> UserSession:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )

        assignments = await self.role_assignment_repo.get_by_user_id(user_id)

        doc_type = user.document_type
        # Hash, no el número en claro: la sesión se cachea en Redis y solo se usa para
        # resolver al deudor propio (get_self_identity), que ya busca por hash.
        doc_number_hash = user.document_number_hash
        must_change_pw = user.must_change_password
        mfa_enabled = user.mfa_enabled

        if not assignments:
            session = UserSession(
                user_id=user_id,
                full_name=user.full_name,
                email=user.email,
                role=UserRole.USER,
                scope=UserScope.SELF,
                document_type=doc_type,
                document_number_hash=doc_number_hash,
                must_change_password=must_change_pw,
                mfa_enabled=mfa_enabled,
            )
        else:
            scopes = {a.scope for a in assignments}

            if UserScope.GLOBAL in scopes:
                global_assignment = next(
                    a for a in assignments if a.scope == UserScope.GLOBAL
                )
                session = UserSession(
                    user_id=user_id,
                    full_name=user.full_name,
                    email=user.email,
                    role=global_assignment.role,
                    scope=UserScope.GLOBAL,
                    document_type=doc_type,
                    document_number_hash=doc_number_hash,
                    mfa_enabled=mfa_enabled,
                )
            elif UserScope.SELF in scopes and UserScope.ORGANIZATION not in scopes:
                self_assignment = next(
                    a for a in assignments if a.scope == UserScope.SELF
                )
                session = UserSession(
                    user_id=user_id,
                    full_name=user.full_name,
                    email=user.email,
                    role=self_assignment.role,
                    scope=UserScope.SELF,
                    document_type=doc_type,
                    document_number_hash=doc_number_hash,
                    mfa_enabled=mfa_enabled,
                )
            else:
                memberships = await self.membership_repo.get_by_user_id(user_id)
                org_ids = [m.organization_id for m in memberships]
                org_models = {
                    str(o.id): o for o in await self.org_repo.get_by_ids(org_ids)
                }
                assignment_by_org = {
                    str(a.organization_id): a
                    for a in assignments
                    if a.organization_id is not None
                }
                overrides_by_org = (
                    await self.permission_assignment_repo.get_overrides_for_user_orgs(
                        user_id, org_ids
                    )
                )
                orgs = {}
                for m in memberships:
                    org_id_str = str(m.organization_id)
                    assignment = assignment_by_org.get(org_id_str)
                    org = org_models.get(org_id_str)
                    if assignment and org:
                        base = get_base_permissions(assignment.role)
                        overrides = overrides_by_org.get(m.organization_id, [])
                        grants = {
                            name
                            for name, effect in overrides
                            if effect == PermissionEffect.GRANT
                        }
                        revokes = {
                            name
                            for name, effect in overrides
                            if effect == PermissionEffect.REVOKE
                        }
                        orgs[org_id_str] = OrgSessionEntry(
                            role=assignment.role,
                            org_name=org.name,
                            permissions=(base | grants) - revokes,
                            verification_status=org.verification_status,
                            created_at=org.created_at,
                        )
                effective_role = (
                    UserRole.ADMIN
                    if any(entry.role == UserRole.ADMIN for entry in orgs.values())
                    else UserRole.USER
                )
                session = UserSession(
                    user_id=user_id,
                    full_name=user.full_name,
                    email=user.email,
                    role=effective_role,
                    document_type=doc_type,
                    document_number_hash=doc_number_hash,
                    scope=UserScope.ORGANIZATION,
                    mfa_enabled=mfa_enabled,
                    orgs=orgs,
                )

        session.profile_photo_url = user.profile_photo_url
        session.identity_verification_status = user.identity_verification_status
        await self.redis.set_json(session_key(user_id), session)
        return session

    async def get_profile(self, user_id: uuid.UUID) -> UserModel:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado.",
            )
        return user

    async def soft_delete_user(self, session: UserSession, user_id: uuid.UUID) -> None:
        await self.assert_can_manage_user(session, user_id)
        admin_org_ids = await self.role_assignment_repo.get_admin_org_ids(user_id)
        if admin_org_ids and not session.is_global:
            # Dar de baja a quien administra una organización arrastra la organización
            # completa (deudores, portafolios, reportes...): no es un poder de admin de
            # organización ni de quien solo gestiona usuarios.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Solo un administrador global puede eliminar a quien "
                    "administra una organización."
                ),
            )

        for org_id in admin_org_ids:
            await self._org_service.soft_delete_organization(org_id)

        remaining_memberships = await self.membership_repo.get_by_user_id(user_id)
        to_delete = [
            m for m in remaining_memberships if m.organization_id not in admin_org_ids
        ]
        await self.membership_repo.delete_many(to_delete)

        user = await self.user_repo.get_by_id(user_id)
        if user is not None:
            await self.user_repo.delete(user)
        await self._revoke_sessions(user_id)

    async def _build_role_entries(
        self, assignments: list[RoleAssignmentModel]
    ) -> list[RoleEntrySchema]:
        org_ids = [a.organization_id for a in assignments if a.organization_id]
        orgs = (
            {o.id: o for o in await self.org_repo.get_by_ids(org_ids)}
            if org_ids
            else {}
        )
        return [
            RoleEntrySchema(
                role=a.role.value,
                scope=a.scope.value,
                org_id=str(a.organization_id) if a.organization_id else None,
                org_name=(
                    orgs[a.organization_id].name
                    if a.organization_id and a.organization_id in orgs
                    else None
                ),
            )
            for a in assignments
        ]

    async def _enrich_users(
        self, users: list[UserModel]
    ) -> list[AdminUserSummarySchema]:
        if not users:
            return []
        user_ids = [u.id for u in users]
        assignments = await self.role_assignment_repo.get_by_user_ids(user_ids)
        org_ids = list({a.organization_id for a in assignments if a.organization_id})
        orgs = (
            {o.id: o for o in await self.org_repo.get_by_ids(org_ids)}
            if org_ids
            else {}
        )

        assignments_by_user: dict[uuid.UUID, list[RoleAssignmentModel]] = {}
        for a in assignments:
            assignments_by_user.setdefault(a.user_id, []).append(a)

        return [
            AdminUserSummarySchema(
                id=u.id,
                full_name=u.full_name,
                email=u.email,
                phone_number=u.phone_number,
                is_active=u.is_active,
                created_at=u.created_at,
                deleted_at=u.deleted_at,
                roles=[
                    RoleEntrySchema(
                        role=a.role.value,
                        scope=a.scope.value,
                        org_id=str(a.organization_id) if a.organization_id else None,
                        org_name=(
                            orgs[a.organization_id].name
                            if a.organization_id and a.organization_id in orgs
                            else None
                        ),
                    )
                    for a in assignments_by_user.get(u.id, [])
                ],
            )
            for u in users
        ]

    async def get_accessible_users(
        self, org_ids: list[uuid.UUID] | None = None, include_deleted: bool = False
    ) -> list[AdminUserSummarySchema]:
        users = list(
            await self.user_repo.get_accessible(
                org_ids=org_ids, include_deleted=include_deleted
            )
        )
        return await self._enrich_users(users)

    async def _revoke_sessions(self, user_id: uuid.UUID) -> None:
        """Cierra la sesión cacheada y el refresh token del usuario: la sesión
        vive en Redis (3 h renovables) sin volver a consultar la base, así que
        sin esto un usuario dado de baja, desactivado o con permisos cambiados
        conserva lo que tenía."""
        await AuthTokenService().revoke_refresh_token(user_id)
        await self.redis.delete(session_key(user_id))
        await self.redis.delete(mfa_verified_key(user_id))

    async def assert_can_manage_user(
        self, session: UserSession, target_user_id: uuid.UUID
    ) -> None:
        """El caller puede ver/editar/eliminar target_user_id si es global, es el
        propio usuario, o gestiona a ese usuario en TODAS las organizaciones donde
        este figura: siendo admin de la organización, o con ORG_USERS cuando el
        objetivo no es admin de ella.

        Un usuario que además pertenece a organizaciones que el caller no
        gestiona, o que es personal global, no se toca desde una organización:
        los cambios sobre su cuenta (correo, MFA, estado) afectarían a otros
        tenants."""
        if session.is_global or session.user_id == target_user_id:
            return
        denied = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado."
        )
        if session.scope != UserScope.ORGANIZATION:
            raise denied
        if await self.role_assignment_repo.get_global_user_ids([target_user_id]):
            raise denied
        memberships = await self.membership_repo.get_by_user_id(target_user_id)
        target_org_ids = {str(m.organization_id) for m in memberships}
        if not target_org_ids or not target_org_ids <= set(session.orgs):
            raise denied
        target_admin_org_ids = {
            str(o)
            for o in await self.role_assignment_repo.get_admin_org_ids(target_user_id)
        }
        for org_id in target_org_ids:
            entry = session.orgs[org_id]
            manages = entry.role == UserRole.ADMIN or (
                ORG_USERS in entry.permissions and org_id not in target_admin_org_ids
            )
            if not manages:
                raise denied

    async def get_user_detail(
        self, session: UserSession, user_id: uuid.UUID
    ) -> AdminUserDetailSchema:
        await self.assert_can_manage_user(session, user_id)
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )
        assignments = await self.role_assignment_repo.get_by_user_id(user_id)
        roles = await self._build_role_entries(assignments)
        return AdminUserDetailSchema(
            id=user.id,
            full_name=user.full_name,
            firstname=user.firstname,
            lastname=user.lastname,
            email=user.email,
            phone_number=user.phone_number,
            auth_provider=user.auth_provider.value,
            document_type=user.document_type,
            document_number=(
                encrypt_service.decrypt_to_str(user.document_number)
                if user.document_number
                else None
            ),
            is_active=user.is_active,
            is_email_verified=user.is_email_verified,
            is_phone_verified=user.is_phone_verified,
            mfa_enabled=user.mfa_enabled,
            is_active_sessions=user.is_active_sessions,
            created_at=user.created_at,
            updated_at=user.updated_at,
            profile_photo_url=user.profile_photo_url,
            roles=roles,
        )

    async def update_user(
        self, session: UserSession, user_id: uuid.UUID, data: UpdateUserSchema
    ) -> AdminUserDetailSchema:
        await self.assert_can_manage_user(session, user_id)
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )
        if data.firstname is not None:
            user.firstname = data.firstname
        if data.lastname is not None:
            user.lastname = data.lastname
        if data.email is not None:
            user.email = data.email
        if data.phone_number is not None:
            user.phone_number = data.phone_number
        if data.is_active is not None:
            user.is_active = data.is_active
        if data.document_type is not None:
            await self._country_service.require_valid_document(
                data.document_type, DocumentScope.PERSON, country_code=user.nationality
            )
            user.document_type = data.document_type
        if data.document_number is not None:
            if data.document_number == "":
                user.document_number = None
                user.document_number_hash = None
            else:
                user.document_number = encrypt_service.encrypt_to_str(
                    data.document_number
                )
                user.document_number_hash = encrypt_service.hash_document(
                    data.document_number
                )
        if data.mfa_enabled is not None:
            user.mfa_enabled = data.mfa_enabled
        await self.user_repo.update(user)
        if user_id != session.user_id:
            # Correo, documento, MFA o estado cambian lo que la sesión cacheada afirma
            # (o si el usuario puede seguir entrando): se obliga a reconstruirla.
            await self._revoke_sessions(user_id)
        return await self.get_user_detail(session, user_id)

    async def update_profile_photo(
        self, user_id: uuid.UUID, file: UploadFile
    ) -> ProfilePhotoSchema:
        """Sustituye la foto de perfil.

        La anterior se borra al final y no antes: si la subida de la nueva falla, el
        usuario se queda con la que tenía en vez de sin ninguna.
        """
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado."
            )

        # Caso 1:1: la foto la apunta `usuarios.id_documento_foto_perfil`, así que
        # no hay tabla de unión ni categoría — la columna que la referencia ya
        # dice qué es.
        document = await self._document_service.store(
            file=file,
            domain=USER_DOCUMENT_STORAGE_DOMAIN,
            owner_id=str(user_id),
            uploaded_by=user_id,
        )

        previous_document_id = user.profile_photo_document_id
        user.profile_photo_document_id = document.id
        await self.user_repo.update(user)

        if previous_document_id is not None and previous_document_id != document.id:
            await self._document_service.delete_by_id(previous_document_id)

        await self.get_user_session(user_id)
        logger.debug(
            "[profile-photo] service update done user_id=%s document_id=%s",
            user_id,
            document.id,
        )
        return ProfilePhotoSchema(profile_photo_url=user.profile_photo_url)

    async def get_profile_photo_content(self, user_id: uuid.UUID) -> Response:
        user = await self.user_repo.get_by_id(user_id)
        if user is None or user.profile_photo_document_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El usuario no tiene foto de perfil.",
            )
        # El ownership ya está resuelto: el id salió de la propia fila del usuario.
        document = await self._document_service.get_by_id(
            user.profile_photo_document_id
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El usuario no tiene foto de perfil.",
            )
        return await self._document_service.to_content_response(document)

    async def get_dismissed_tours(self, user_id: uuid.UUID) -> list[str]:
        prefs = await self.preferences_repo.get_by_user_id(user_id)
        return prefs.dismissed_tours if prefs else []

    @staticmethod
    def _validate_tour_key(tour_key: str) -> None:
        if tour_key not in TOUR_KEYS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El tour indicado no existe.",
            )

    async def dismiss_tour(self, user_id: uuid.UUID, tour_key: str) -> list[str]:
        self._validate_tour_key(tour_key)
        prefs = await self.preferences_repo.dismiss_tour(user_id, tour_key)
        return prefs.dismissed_tours

    async def restore_tour(self, user_id: uuid.UUID, tour_key: str) -> list[str]:
        self._validate_tour_key(tour_key)
        prefs = await self.preferences_repo.restore_tour(user_id, tour_key)
        return prefs.dismissed_tours if prefs else []

    async def restore_all_tours(self, user_id: uuid.UUID) -> list[str]:
        prefs = await self.preferences_repo.restore_all_tours(user_id)
        return prefs.dismissed_tours if prefs else []

    async def restore_user(self, user_id: uuid.UUID) -> UserModel | None:
        user = await self.user_repo.get_by_id_including_deleted(user_id)
        if user is None or user.deleted_at is None:
            return user
        await self.user_repo.restore(user)
        admin_org_ids = await self.role_assignment_repo.get_admin_org_ids(user_id)
        for org_id in admin_org_ids:
            await self._org_service.restore_organization(org_id)
        all_memberships = await self.membership_repo.get_by_user_id_including_deleted(
            user_id
        )
        to_restore = [
            m
            for m in all_memberships
            if m.organization_id not in admin_org_ids and m.deleted_at is not None
        ]
        await self.membership_repo.restore_many(to_restore)
        return user

    async def get_available_for_chat(self, session: UserSession) -> list:
        role = session.role
        scope = session.scope
        self_id = session.user_id

        if scope == UserScope.GLOBAL:
            users = await self.user_repo.get_all_active_except(self_id)

        elif scope == UserScope.ORGANIZATION:
            org_ids = [uuid.UUID(oid) for oid in session.orgs.keys()]
            if role == UserRole.CUSTOMER_SERVICE:
                users = await self.user_repo.get_cs_org_members_and_global_cs(
                    self_id, org_ids
                )
            else:
                users = await self.user_repo.get_active_org_members(self_id, org_ids)

        elif scope == UserScope.SELF:
            users = list(await self.user_repo.get_cs_agents_for_self_user(self_id))
            extra = await self.user_repo.get_global_admins_chatted_recently(self_id)
            seen = {u.id for u in users}
            users += [u for u in extra if u.id not in seen]

        else:
            users = []

        if scope != UserScope.SELF:
            extra = await self.user_repo.get_global_admins_chatted_recently(self_id)
            seen = {u.id for u in users}
            users = list(users) + [u for u in extra if u.id not in seen]

        online_ids = ws_manager.online_user_ids()
        return [
            ChatAvailableUserSchema(
                id=u.id,
                full_name=u.full_name,
                profile_photo_url=u.profile_photo_url,
                is_online=u.id in online_ids,
            )
            for u in users
        ]

    @property
    def _org_service(self) -> OrganizationService:
        return OrganizationService(
            self.org_repo, self.membership_repo, self.role_assignment_repo
        )
