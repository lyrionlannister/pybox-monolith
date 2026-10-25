"""Registro, login, OAuth y recuperación de contraseña de usuarios."""

import uuid
from typing import cast

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import DocumentScope
from app_platform.countries.repository.country_repository import CountryRepository
from app_platform.countries.services.country_service import CountryService
from core.config.logger import logger
from core.database.redis import redis_client
from core.security.services.auth_token_service import AuthTokenService
from core.security.services.encrypt_service import encrypt_service
from core.security.services.password_hasher_service import PasswordHasherService
from identity.auth.enums.auth_enums import AuthProvider
from identity.auth.enums.notification_enums import VerificationChannel
from identity.auth.exceptions import (
    CodeAlreadyUsedException,
    CodeExpiredException,
    CodeNotFoundException,
)
from identity.auth.factories import get_verification_service
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.models.role_assignment_model import RoleAssignmentModel
from identity.users.models.user_model import UserModel
from identity.users.repository.role_assignment_repository import (
    RoleAssignmentRepository,
)
from identity.users.repository.user_repository import UserRepository
from identity.users.schemas.user_session_schema import mfa_verified_key, session_key
from identity.users.services.user_service import UserService

from ..schemas.auth_schemas import (
    AuthResponse,
    ProviderAuth,
    ProviderLogin,
    UserCreate,
    UserLogin,
)
from ..utils.auth_utils import (
    mask_email,
    mask_phone,
    normalize_email,
    normalize_optional,
    require_value,
    resolve_auth_provider,
)
from .oauth_provider_service import OAuthProviderService, ProviderProfile


class AuthService:
    def __init__(
        self,
        user_repository: UserRepository,
        role_assignment_repository: RoleAssignmentRepository,
        password_hasher: PasswordHasherService | None = None,
        token_service: AuthTokenService | None = None,
        oauth_provider_service: OAuthProviderService | None = None,
        user_service: UserService | None = None,
        session: AsyncSession | None = None,
    ):
        self.user_repository = user_repository
        self.role_assignment_repository = role_assignment_repository
        self.password_hasher = password_hasher or PasswordHasherService()
        self.token_service = token_service or AuthTokenService()
        self.oauth_provider_service = oauth_provider_service or OAuthProviderService()
        self._user_service = user_service
        self._session = session
        # Validación de país/documento contra la DB (paises / paises_tipos_documento),
        # reemplaza los enums estáticos Nationality / UserDocumentType.
        self._country_service = CountryService(
            CountryRepository(user_repository.session)
        )

    async def register_and_authenticate(
        self, user_data: UserCreate, role: UserRole, scope: UserScope
    ) -> AuthResponse:
        user = await self.register_user(user_data)
        await self.role_assignment_repository.add(
            RoleAssignmentModel(user_id=user.id, role=role, scope=scope)
        )
        return await self._build_response(user, AuthProvider.SELF)

    async def register_user(self, user_data: UserCreate) -> UserModel:
        email = normalize_email(user_data.email)
        phone_number = require_value(
            user_data.phone_number, "El número de teléfono es obligatorio."
        )
        nationality = await self._country_service.require_valid_country(
            user_data.nationality
        )
        document_type = await self._country_service.require_valid_document(
            user_data.document_type, DocumentScope.PERSON, country_code=nationality
        )
        document_number = user_data.document_number or None

        if await self.user_repository.get_by_email(email):
            raise ValueError("El correo electrónico ya está registrado.")

        if await self.user_repository.get_by_phone_number(phone_number):
            raise ValueError("El número de teléfono ya está registrado.")

        document_number_hash = (
            encrypt_service.hash_document(document_number) if document_number else None
        )
        if document_type and document_number_hash:
            if await self.user_repository.get_by_document(
                document_type, document_number_hash
            ):
                raise ValueError("El documento ya está registrado.")

        user = UserModel(
            firstname=require_value(user_data.firstname, "El nombre es obligatorio."),
            lastname=require_value(user_data.lastname, "El apellido es obligatorio."),
            email=email,
            hashed_password=self.password_hasher.hash_password(user_data.password),
            phone_number=phone_number,
            auth_provider=AuthProvider.SELF,
            nationality=nationality,
            document_type=document_type,
            document_number=(
                encrypt_service.encrypt_to_str(document_number)
                if document_number
                else None
            ),
            document_number_hash=document_number_hash,
        )

        user = await self.user_repository.add(user)
        logger.info("[auth] register | user_id=%s", user.id)
        return user

    async def authenticate_user(self, user_data: UserLogin) -> AuthResponse:
        email = normalize_email(user_data.email)
        password = require_value(user_data.password, "La contraseña es obligatoria.")

        user = await self.user_repository.get_by_email(email)
        if not user:
            raise ValueError("Credenciales inválidas.")

        stored_hash = cast(str | None, user.hashed_password)
        if not stored_hash:
            raise ValueError("Este usuario debe autenticarse con proveedor externo.")

        is_valid, new_hash = self.password_hasher.verify_and_maybe_rehash(
            stored_hash, password
        )
        if not is_valid:
            logger.warning(
                "[auth] login_failed | user_id=%s reason=invalid_password", user.id
            )
            raise ValueError("Credenciales inválidas.")

        if new_hash:
            setattr(user, "hashed_password", new_hash)
            user = await self.user_repository.update(user)

        logger.info("[auth] login | user_id=%s provider=SELF", user.id)
        return await self._build_response(user, AuthProvider.SELF)

    async def authenticate_provider_user(
        self,
        provider_data: ProviderLogin,
        role: UserRole = UserRole.ADMIN,
        scope: UserScope = UserScope.ORGANIZATION,
    ) -> AuthResponse:
        provider = resolve_auth_provider(provider_data.provider)
        token = require_value(str(provider_data.token), "El token es obligatorio.")

        if provider == AuthProvider.SELF:
            raise ValueError("SELF no es un proveedor externo.")

        provider_profile = self.oauth_provider_service.verify_provider_token(
            provider, token
        )
        user, is_new = await self._get_or_create_provider_user(
            provider_profile, provider_data
        )
        if not is_new:
            logger.warning(
                "[auth] oauth_register_failed | provider=%s reason=already_exists "
                "user_id=%s",
                provider.value,
                user.id,
            )
            raise ValueError(
                "Ya tienes una cuenta registrada con este proveedor. Inicia sesión."
            )
        await self.role_assignment_repository.add(
            RoleAssignmentModel(user_id=user.id, role=role, scope=scope)
        )
        logger.info(
            "[auth] oauth_register | user_id=%s provider=%s", user.id, provider.value
        )
        return await self._build_response(user, provider)

    async def authenticate_existing_provider_user(
        self, provider_data: ProviderAuth
    ) -> AuthResponse:
        provider = resolve_auth_provider(provider_data.provider)
        token = require_value(str(provider_data.token), "El token es obligatorio.")

        if provider == AuthProvider.SELF:
            raise ValueError("SELF no es un proveedor externo.")

        provider_profile = self.oauth_provider_service.verify_provider_token(
            provider, token
        )
        user = await self._get_provider_user_or_link_email(provider_profile)
        if not user:
            logger.warning(
                "[auth] oauth_login_failed | provider=%s reason=user_not_found",
                provider.value,
            )
            raise ValueError(
                "No encontramos una cuenta asociada a Google. Regístrate primero "
                "para completar tu perfil."
            )
        logger.info(
            "[auth] oauth_login | user_id=%s provider=%s", user.id, provider.value
        )
        return await self._build_response(user, provider)

    async def refresh_tokens(self, refresh_token: str) -> AuthResponse:
        try:
            payload = jwt.decode(
                refresh_token,
                self.token_service.secret_key,
                algorithms=[self.token_service.ALGORITHM],
            )
        except jwt.ExpiredSignatureError as e:
            raise ValueError("El refresh token expiró.") from e
        except jwt.InvalidTokenError as e:
            raise ValueError("El refresh token no es válido.") from e

        user_id = uuid.UUID(str(payload["sub"]))
        jti: str = payload["jti"]

        if not await self.token_service.verify_refresh_token(user_id, jti):
            raise ValueError("Sesión inválida o ya cerrada.")

        user = await self.user_repository.get_by_id(user_id)
        if not user or not user.is_active:
            raise ValueError("Usuario no encontrado.")

        logger.info("[auth] token_refresh | user_id=%s", user_id)
        await self.token_service.revoke_refresh_token(user_id)
        return await self._build_response(
            user, cast(AuthProvider, user.auth_provider), new_login=False
        )

    async def logout(self, user_id: uuid.UUID) -> None:
        logger.info("[auth] logout | user_id=%s", user_id)
        await self.token_service.revoke_refresh_token(user_id)
        await redis_client.delete(session_key(user_id))
        await redis_client.delete(mfa_verified_key(user_id))
        user = await self.user_repository.get_by_id(user_id)
        if user:
            setattr(user, "is_active_sessions", False)
            await self.user_repository.update(user)

    async def _get_or_create_provider_user(
        self,
        provider_profile: ProviderProfile,
        provider_data: ProviderLogin,
    ) -> tuple[UserModel, bool]:
        user = await self._get_provider_user_or_link_email(provider_profile)
        if user:
            return user, False

        phone_number = normalize_optional(provider_data.phone_number)
        nationality = await self._country_service.require_valid_country(
            provider_data.nationality, required=False
        )

        if phone_number and await self.user_repository.get_by_phone_number(
            phone_number
        ):
            raise ValueError("El número de teléfono ya está registrado.")

        doc_type = await self._country_service.require_valid_document(
            provider_data.document_type, DocumentScope.PERSON, country_code=nationality
        )
        doc_number = provider_data.document_number or None
        doc_number_hash = (
            encrypt_service.hash_document(doc_number) if doc_number else None
        )

        user = UserModel(
            firstname=(
                normalize_optional(provider_data.firstname)
                or normalize_optional(provider_profile.firstname)
                or provider_profile.email.split("@", 1)[0]
            ),
            lastname=(
                normalize_optional(provider_data.lastname)
                or normalize_optional(provider_profile.lastname)
                or ""
            ),
            email=provider_profile.email,
            hashed_password=None,
            phone_number=phone_number,
            auth_provider=provider_profile.provider,
            provider_user_id=provider_profile.provider_user_id,
            nationality=nationality,
            document_type=doc_type,
            document_number=(
                encrypt_service.encrypt_to_str(doc_number) if doc_number else None
            ),
            document_number_hash=doc_number_hash,
        )
        return await self.user_repository.add(user), True

    async def _get_provider_user_or_link_email(
        self,
        provider_profile: ProviderProfile,
    ) -> UserModel | None:
        user = await self.user_repository.get_by_provider_identity(
            provider_profile.provider,
            provider_profile.provider_user_id,
        )
        if user:
            return user

        user = await self.user_repository.get_by_email(provider_profile.email)
        if not user:
            return None

        setattr(user, "auth_provider", provider_profile.provider)
        setattr(user, "provider_user_id", provider_profile.provider_user_id)
        return await self.user_repository.update(user)

    async def _build_response(
        self, user: UserModel, auth_provider: AuthProvider, *, new_login: bool = True
    ) -> AuthResponse:
        setattr(user, "is_active_sessions", True)
        await self.user_repository.update(user)
        if new_login:
            # Cada login nuevo vuelve a exigir el segundo factor, aunque quede un flag
            # de una sesión anterior sin expirar todavía (`refresh_tokens` pasa
            # new_login=False: renovar el access token cada hora no debe re-pedir MFA).
            await redis_client.delete(mfa_verified_key(user.id))
        access_token = self.token_service.generate_access_token(user, auth_provider)
        refresh_token = await self.token_service.generate_refresh_token(user.id)
        if self._user_service is not None:
            await self._user_service.get_user_session(user.id)
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            auth_provider=auth_provider,
        )

    async def change_password(
        self, user_id: uuid.UUID, current_password: str, new_password: str
    ) -> None:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise ValueError("Usuario no encontrado.")
        stored_hash = cast(str | None, user.hashed_password)
        if not stored_hash:
            raise ValueError(
                "Este usuario no tiene contraseña configurada. Usa tu proveedor OAuth."
            )
        is_valid, _ = self.password_hasher.verify_and_maybe_rehash(
            stored_hash, current_password
        )
        if not is_valid:
            raise ValueError("La contraseña actual es incorrecta.")
        user.hashed_password = self.password_hasher.hash_password(new_password)
        await self.user_repository.update(user)
        await self.token_service.revoke_refresh_token(user_id)
        await redis_client.delete(session_key(user_id))
        await redis_client.delete(mfa_verified_key(user_id))
        logger.info("[auth] change_password | user_id=%s", user_id)

    async def lookup_user_for_reset(
        self, document_type: str, document_number: str
    ) -> dict:
        # Respuesta uniforme exista o no la cuenta (ambos campos en None si no existe):
        # evita que el status code / la forma de la respuesta sirvan de oráculo para
        # enumerar documentos registrados. Combinado con el rate limit del endpoint.
        dt = document_type
        doc_hash = encrypt_service.hash_document(document_number)
        user = await self.user_repository.get_by_document(dt, doc_hash)
        if user is None:
            return {"masked_email": None, "masked_phone": None}
        return {
            "masked_email": mask_email(cast(str, user.email)) if user.email else None,
            "masked_phone": (
                mask_phone(cast(str, user.phone_number)) if user.phone_number else None
            ),
        }

    async def verify_reset_code(
        self,
        document_type: str,
        document_number: str,
        code: str,
        channel: VerificationChannel,
    ) -> None:
        if self._session is None:
            raise RuntimeError("Session requerida para verificar OTP.")
        dt = document_type
        doc_hash = encrypt_service.hash_document(document_number)
        user = await self.user_repository.get_by_document(dt, doc_hash)
        if user is None:
            raise ValueError("Credenciales inválidas.")
        svc = get_verification_service(channel, self._session)
        try:
            await svc.peek_code(user.id, code)
        except CodeNotFoundException as e:
            raise ValueError("Código incorrecto.") from e
        except CodeExpiredException as e:
            raise ValueError("El código ha expirado.") from e
        except CodeAlreadyUsedException as e:
            raise ValueError("El código ya fue utilizado.") from e
        logger.info("[auth] verify_reset_code | user_id=%s", user.id)

    async def send_reset_code(
        self, document_type: str, document_number: str, channel: VerificationChannel
    ) -> None:
        if self._session is None:
            raise RuntimeError("Session requerida para enviar OTP.")
        dt = document_type
        doc_hash = encrypt_service.hash_document(document_number)
        user = await self.user_repository.get_by_document(dt, doc_hash)
        if user is None:
            # Mismo criterio que `lookup_user_for_reset`: no confirmar por status
            # code si el documento existe o no, para no servir de oráculo.
            return
        svc = get_verification_service(channel, self._session)
        await svc.send_code(user)
        logger.info(
            "[auth] send_reset_code | user_id=%s channel=%s", user.id, channel.value
        )

    async def reset_password(
        self,
        document_type: str,
        document_number: str,
        code: str,
        channel: VerificationChannel,
        new_password: str,
    ) -> None:
        if self._session is None:
            raise RuntimeError("Session requerida para verificar OTP.")
        dt = document_type
        doc_hash = encrypt_service.hash_document(document_number)
        user = await self.user_repository.get_by_document(dt, doc_hash)
        if user is None:
            raise ValueError("Credenciales inválidas.")
        svc = get_verification_service(channel, self._session)
        try:
            await svc.verify_code(user.id, code)
        except CodeNotFoundException as e:
            raise ValueError("Código no encontrado.") from e
        except CodeExpiredException as e:
            raise ValueError("El código ha expirado.") from e
        except CodeAlreadyUsedException as e:
            raise ValueError("El código ya fue utilizado.") from e
        user.hashed_password = self.password_hasher.hash_password(new_password)
        await self.user_repository.update(user)
        await self.token_service.revoke_refresh_token(user.id)
        await redis_client.delete(session_key(user.id))
        await redis_client.delete(mfa_verified_key(user.id))
        logger.info("[auth] reset_password | user_id=%s", user.id)

    def _provider_value(
        self,
        provider_data: ProviderLogin,
        key: str,
        fallback: str | None,
        message: str,
    ) -> str:
        value = normalize_optional(getattr(provider_data, key, None)) or fallback
        return require_value(value or "", message)
