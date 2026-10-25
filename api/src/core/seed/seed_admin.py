"""Crea el usuario admin inicial (global) si todavía no existe ninguno."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.countries.enums.country_enums import Nationality, UserDocumentType
from core.config.logger import logger
from core.config.seed_admin_config import SeedAdminConfig
from core.security.services.encrypt_service import encrypt_service
from core.security.services.password_hasher_service import PasswordHasherService
from identity.auth.enums.auth_enums import AuthProvider
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.models.role_assignment_model import RoleAssignmentModel
from identity.users.models.user_model import UserModel


async def seed_admin(session: AsyncSession) -> None:
    count = (
        await session.execute(select(func.count()).select_from(UserModel))
    ).scalar()
    if count:
        return

    cfg = SeedAdminConfig()
    hasher = PasswordHasherService()

    user = UserModel(
        firstname=cfg.firstname,
        lastname=cfg.lastname,
        email=cfg.email.lower(),
        hashed_password=hasher.hash_password(cfg.password),
        phone_number=cfg.phone,
        auth_provider=AuthProvider.SELF,
        nationality=Nationality(cfg.nationality),
        document_type=UserDocumentType(cfg.doc_type),
        document_number=encrypt_service.encrypt_to_str(cfg.doc_number),
        document_number_hash=encrypt_service.hash_document(cfg.doc_number),
        is_email_verified=True,
        is_phone_verified=True,
        mfa_enabled=False,
    )
    session.add(user)
    await session.flush()

    session.add(
        RoleAssignmentModel(
            user_id=user.id,
            role=UserRole.ADMIN,
            scope=UserScope.GLOBAL,
        )
    )
    logger.info("[seed] admin_created | user_id=%s", user.id)
