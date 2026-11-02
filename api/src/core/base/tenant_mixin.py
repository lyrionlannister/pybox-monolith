"""Mixin de `organization_id` para modelos propios de una organización."""

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class TenantMixin:
    """`organization_id` en su forma más común entre los modelos que lo declaran:
    FK obligatoria a `entidades.id`, indexada, columna `id_organizacion`.

    Se aplica solo a los modelos cuya definición coincidía exactamente con esta --
    los que la tenían nullable, con FK `use_alter` o con un nombre de columna
    distinto (p. ej. `id_entidad`) se quedan con su propia declaración porque esa
    diferencia es intencional (ver Fase 0/3 de la auditoría de modelos base).
    """

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id"),
        nullable=False,
        index=True,
        name="id_organizacion",
    )
