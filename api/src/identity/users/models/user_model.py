"""Usuario de la plataforma: credenciales, identidad y estado de sesión."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from identity.auth.enums.auth_enums import AuthProvider
from identity.organizations.models.organization_membership_model import (
    OrganizationMembershipModel,
)
from identity.users.enums.user_enums import IdentityVerificationStatus


class UserModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "usuarios"
    __table_args__ = (
        UniqueConstraint(
            "proveedor_autenticacion",
            "id_usuario_proveedor",
            name="uq_usuarios_proveedor_usuario",
        ),
    )

    firstname: Mapped[str] = mapped_column(String(255), nullable=False, name="nombre")
    lastname: Mapped[str] = mapped_column(String(255), nullable=False, name="apellido")
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, name="correo_electronico"
    )
    hashed_password: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="contrasena_hash"
    )
    phone_number: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, name="numero_telefono"
    )
    auth_provider: Mapped[AuthProvider] = mapped_column(
        ENUM(
            AuthProvider,
            name="proveedor_autenticacion",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AuthProvider.SELF,
        name="proveedor_autenticacion",
    )
    provider_user_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="id_usuario_proveedor"
    )
    nationality: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("paises.codigo"), nullable=True, name="nacionalidad"
    )
    document_type: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("tipos_documento.codigo"),
        nullable=True,
        name="tipo_documento",
    )
    document_number: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="numero_documento"
    )
    document_number_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True, name="numero_documento_hash"
    )
    # db-schema-design, ítem 3: puntero "al vigente" hacia `documentos`, misma forma que
    # OrganizationModel.fiscal_document_id — pero acá NO se puede cerrar con una FK
    # compuesta: `documentos.owner_id` (el lado polimórfico, ítem 2) es String(64)
    # genérico porque sirve a 6 tipos de dueño distintos, y Postgres no compara ese tipo
    # contra `usuarios.id` (UUID) sin un cast, que una FK plana no admite. Que el
    # documento apuntado sea realmente de este usuario y de categoría foto_perfil queda
    # protegido únicamente por UserService.update_profile_photo (crea el documento y
    # asigna el puntero en la misma operación) — riesgo aceptado y documentado, no
    # implícito.
    profile_photo_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documentos.id", use_alter=True),
        nullable=True,
        name="id_documento_foto_perfil",
        index=True,
    )
    # El documento de identidad subido no cuelga de un puntero propio: se sube como
    # adjunto (documentos_ticket) del ticket de validación que crea
    # OnboardingService.submit_identity_document — mismo mecanismo que cualquier otro
    # adjunto de ticket, sin necesidad de una columna/FK nueva acá.
    identity_verification_status: Mapped[IdentityVerificationStatus] = mapped_column(
        ENUM(
            IdentityVerificationStatus,
            name="estado_verificacion_identidad",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=IdentityVerificationStatus.NOT_SUBMITTED,
        name="estado_verificacion_identidad",
    )
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, name="correo_verificado"
    )
    is_phone_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, name="telefono_verificado"
    )
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="mfa_habilitado"
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, name="debe_cambiar_password"
    )
    is_active_sessions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, name="sesion_activa"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )

    memberships: Mapped[list[OrganizationMembershipModel]] = relationship(
        OrganizationMembershipModel,
        foreign_keys="[OrganizationMembershipModel.user_id]",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    created_memberships: Mapped[list[OrganizationMembershipModel]] = relationship(
        OrganizationMembershipModel,
        foreign_keys="[OrganizationMembershipModel.created_by]",
        back_populates="creator",
    )

    @property
    def full_name(self) -> str:
        return f"{self.firstname.strip()} {self.lastname}"

    @property
    def profile_photo_url(self) -> str | None:
        if self.profile_photo_document_id is None:
            return None
        return f"/users/{self.id}/profile-photo/content"
