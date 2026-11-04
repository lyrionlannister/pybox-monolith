"""Schemas de usuario: resumen, detalle admin y disponibilidad para chat."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from core.base.schema_base import BaseSchema


class UserSummarySchema(BaseSchema):
    id: uuid.UUID = Field(description="ID del usuario")
    full_name: str = Field(description="Nombre completo")
    email: str = Field(description="Correo electrónico")


class ChatAvailableUserSchema(BaseSchema):
    id: uuid.UUID = Field(description="ID del usuario")
    full_name: str = Field(description="Nombre completo")
    profile_photo_url: str | None = Field(
        default=None, description="URL de la foto de perfil"
    )
    is_online: bool = Field(
        default=False, description="Indica si el usuario está en línea"
    )


class RoleEntrySchema(BaseSchema):
    role: str = Field(description="Rol del usuario")
    scope: str = Field(description="Ámbito (GLOBAL u ORGANIZATION)")
    org_id: str | None = Field(default=None, description="ID de la organización")
    org_name: str | None = Field(default=None, description="Nombre de la organización")


class AdminUserSummarySchema(BaseSchema):
    id: uuid.UUID = Field(description="ID del usuario")
    full_name: str = Field(description="Nombre completo")
    email: str = Field(description="Correo electrónico")
    phone_number: str | None = Field(description="Número de teléfono")
    is_active: bool = Field(description="Indica si la cuenta está activa")
    created_at: datetime | None = Field(description="Fecha de creación")
    deleted_at: datetime | None = Field(
        default=None,
        description="Fecha de baja lógica; null si el usuario está vigente",
    )
    roles: list[RoleEntrySchema] = Field(default=[], description="Roles del usuario")


class AdminUserDetailSchema(AdminUserSummarySchema):
    firstname: str = Field(description="Nombre")
    lastname: str = Field(description="Apellido")
    phone_number: str | None = Field(description="Teléfono")
    auth_provider: str = Field(description="Proveedor de autenticación")
    document_type: str | None = Field(description="Tipo de documento")
    document_number: str | None = Field(description="Número de documento")
    is_email_verified: bool = Field(description="Correo verificado")
    is_phone_verified: bool = Field(description="Teléfono verificado")
    mfa_enabled: bool = Field(description="MFA habilitado")
    is_active_sessions: bool = Field(description="Tiene sesiones activas")
    updated_at: datetime | None = Field(description="Última actualización")
    profile_photo_url: str | None = Field(
        default=None, description="URL de foto de perfil"
    )


class UpdateUserSchema(BaseSchema):
    firstname: str | None = Field(default=None, description="Nombre")
    lastname: str | None = Field(default=None, description="Apellido")
    email: str | None = Field(default=None, description="Correo electrónico")
    phone_number: str | None = Field(default=None, description="Teléfono")
    is_active: bool | None = Field(
        default=None, description="Activar o desactivar cuenta"
    )
    document_type: str | None = Field(
        default=None, description="Código del tipo de documento"
    )
    document_number: str | None = Field(default=None, description="Número de documento")
    mfa_enabled: bool | None = Field(
        default=None, description="Habilitar o deshabilitar MFA"
    )
    current_password: str | None = Field(
        default=None,
        description=(
            "Contraseña actual: obligatoria cuando el propio usuario cambia su correo "
            "o desactiva su MFA"
        ),
    )


class ProfilePhotoSchema(BaseSchema):
    profile_photo_url: str = Field(
        description="URL pública de la foto de perfil actualizada"
    )
