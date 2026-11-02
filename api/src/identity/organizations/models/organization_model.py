"""Organización cliente de la plataforma (empresa acreedora)."""

import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from identity.organizations.enums.organization_enums import (
    EntitySectors,
    VerificationStatus,
)


class OrganizationModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "entidades"
    __table_args__ = (
        # db-schema-design, ítem 3 (atributo derivado/redundante sin invariante
        # protegida): id_documento_fiscal/mercantil/representante son punteros "al
        # vigente" hacia `documentos`, que ya es en sí una asociación polimórfica
        # (documentos.id_dueno + ambito) resuelta acá con "Reverse the relationship"
        # (ítem 2). Sin más, nada impedía que el puntero apuntara a un documento de
        # OTRA organización o de otra categoría.
        #
        # Esta FK compuesta cierra la mitad que SÍ es expresable en una constraint:
        # (id_documento_fiscal, id) -> documentos(id, id_organizacion) obliga a que
        # el documento pertenezca a esta misma organización (MATCH SIMPLE: si el
        # puntero es NULL, la fila no se valida). Requiere el UNIQUE(id,
        # id_organizacion) declarado en DocumentModel.
        #
        # Lo que NO cubre: que la categoría del documento sea la correcta (fiscal
        # vs. mercantil vs. representante_legal) — eso no es expresable en una FK
        # de Postgres sin un trigger, y sigue protegido únicamente por
        # OrganizationService, que crea el documento y asigna el puntero en la
        # misma operación (riesgo aceptado y documentado, no implícito).
        #
        # use_alter: cierra el mismo ciclo documentos<->entidades que
        # DocumentModel.organization_id — sin esto no hay orden de CREATE TABLE
        # posible.
        ForeignKeyConstraint(
            ["id_documento_fiscal", "id"],
            ["documentos.id", "documentos.id_organizacion"],
            name="fk_entidades_id_documento_fiscal_documentos",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["id_documento_mercantil", "id"],
            ["documentos.id", "documentos.id_organizacion"],
            name="fk_entidades_id_documento_mercantil_documentos",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["id_documento_representante", "id"],
            ["documentos.id", "documentos.id_organizacion"],
            name="fk_entidades_id_documento_representante_documentos",
            use_alter=True,
        ),
        # Mismo patrón que los tres anteriores (db-schema-design ítems 2/3): el
        # logo es otro puntero "al vigente" hacia `documentos`, cerrado con la
        # misma FK compuesta contra (documentos.id, documentos.id_organizacion)
        # para que Postgres rechace un logo que pertenezca a otra organización. A
        # diferencia de fiscal/mercantil, el logo no tiene columna de "tipo" (no
        # es un documento de verificación).
        ForeignKeyConstraint(
            ["id_documento_logo", "id"],
            ["documentos.id", "documentos.id_organizacion"],
            name="fk_entidades_id_documento_logo_documentos",
            use_alter=True,
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, name="nombre")
    description: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="descripcion"
    )
    country: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("paises.codigo"), nullable=True, name="pais"
    )
    # Sector de la entidad acreedora: obligatorio, se captura al crear la organización
    # (alta directa, registro con representante y onboarding).
    # values_callable para persistir los VALORES del enum y no los NOMBRES.
    sector: Mapped[EntitySectors] = mapped_column(
        ENUM(
            EntitySectors,
            name="sector_entidad",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="sector",
    )

    fiscal_document_type: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("tipos_documento.codigo"),
        nullable=True,
        name="tipo_documento_fiscal",
    )
    fiscal_document_number: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="numero_documento_fiscal"
    )
    # La FK hacia `documentos` de estas tres columnas es la compuesta de
    # __table_args__, no una simple: así Postgres exige además que el documento
    # pertenezca a esta entidad.
    fiscal_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, name="id_documento_fiscal"
    )

    mercantile_document_type: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("tipos_documento.codigo"),
        nullable=True,
        name="tipo_documento_mercantil",
    )
    mercantile_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, name="id_documento_mercantil"
    )
    representative_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, name="id_documento_representante"
    )
    logo_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, name="id_documento_logo"
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        ENUM(
            VerificationStatus,
            name="estado_verificacion",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=VerificationStatus.PENDING,
        name="estado_verificacion",
    )

    memberships = relationship(
        "OrganizationMembershipModel",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
