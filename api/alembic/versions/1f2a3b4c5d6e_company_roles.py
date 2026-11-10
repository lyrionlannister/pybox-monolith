"""company_roles

Roles de empresa (Bloque B del plan de Calendario): cada organizacion define sus
propios roles nombrados -- un conjunto de permisos del catalogo existente (`permisos`,
`permisos_asignados`) -- y los asigna a sus usuarios, sin tocar el motor de roles
fijos (`roles_asignados`/`UserRole`) que sigue gobernando ADMIN/CUSTOMER_SERVICE/USER.

Revision ID: 1f2a3b4c5d6e
Revises: 0c1d2e3f4a5b
Create Date: 2026-11-09 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "1f2a3b4c5d6e"
down_revision: Union[str, None] = "0c1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "roles_empresa",
        sa.Column("id_organizacion", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("eliminado_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["id_organizacion"],
            ["entidades.id"],
            name=op.f("fk_roles_empresa_id_organizacion_entidades"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles_empresa")),
        # Habilita la FK compuesta de usuarios_roles_empresa (db-schema-design item 8).
        sa.UniqueConstraint(
            "id", "id_organizacion", name="uq_roles_empresa_id_organizacion"
        ),
    )
    op.create_index(
        op.f("ix_roles_empresa_id_organizacion"),
        "roles_empresa",
        ["id_organizacion"],
        unique=False,
    )
    op.create_index(
        "uq_rol_empresa_organizacion_nombre",
        "roles_empresa",
        ["id_organizacion", "nombre"],
        unique=True,
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )

    op.create_table(
        "roles_empresa_permisos",
        sa.Column("id_rol_empresa", sa.UUID(), nullable=False),
        sa.Column("id_permiso", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("eliminado_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["id_rol_empresa"],
            ["roles_empresa.id"],
            name=op.f("fk_roles_empresa_permisos_id_rol_empresa_roles_empresa"),
        ),
        sa.ForeignKeyConstraint(
            ["id_permiso"],
            ["permisos.id"],
            name=op.f("fk_roles_empresa_permisos_id_permiso_permisos"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles_empresa_permisos")),
    )
    op.create_index(
        op.f("ix_roles_empresa_permisos_id_rol_empresa"),
        "roles_empresa_permisos",
        ["id_rol_empresa"],
        unique=False,
    )
    op.create_index(
        op.f("ix_roles_empresa_permisos_id_permiso"),
        "roles_empresa_permisos",
        ["id_permiso"],
        unique=False,
    )
    op.create_index(
        "uq_rol_empresa_permiso",
        "roles_empresa_permisos",
        ["id_rol_empresa", "id_permiso"],
        unique=True,
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )

    op.create_table(
        "usuarios_roles_empresa",
        sa.Column("id_usuario", sa.UUID(), nullable=False),
        sa.Column("id_organizacion", sa.UUID(), nullable=False),
        sa.Column("id_rol_empresa", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("eliminado_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["id_usuario"],
            ["usuarios.id"],
            name=op.f("fk_usuarios_roles_empresa_id_usuario_usuarios"),
        ),
        sa.ForeignKeyConstraint(
            ["id_organizacion"],
            ["entidades.id"],
            name=op.f("fk_usuarios_roles_empresa_id_organizacion_entidades"),
        ),
        # Un usuario nunca puede quedar asignado a un rol de OTRA organización:
        # reforzado a nivel de constraint (db-schema-design item 8), no solo por el
        # chequeo del Service.
        sa.ForeignKeyConstraint(
            ["id_rol_empresa", "id_organizacion"],
            ["roles_empresa.id", "roles_empresa.id_organizacion"],
            name="fk_usuarios_roles_empresa_rol_organizacion",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuarios_roles_empresa")),
    )
    op.create_index(
        op.f("ix_usuarios_roles_empresa_id_usuario"),
        "usuarios_roles_empresa",
        ["id_usuario"],
        unique=False,
    )
    op.create_index(
        op.f("ix_usuarios_roles_empresa_id_organizacion"),
        "usuarios_roles_empresa",
        ["id_organizacion"],
        unique=False,
    )
    op.create_index(
        op.f("ix_usuarios_roles_empresa_id_rol_empresa"),
        "usuarios_roles_empresa",
        ["id_rol_empresa"],
        unique=False,
    )
    op.create_index(
        "uq_usuario_rol_empresa",
        "usuarios_roles_empresa",
        ["id_usuario", "id_rol_empresa"],
        unique=True,
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_usuario_rol_empresa",
        table_name="usuarios_roles_empresa",
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )
    op.drop_index(
        op.f("ix_usuarios_roles_empresa_id_rol_empresa"),
        table_name="usuarios_roles_empresa",
    )
    op.drop_index(
        op.f("ix_usuarios_roles_empresa_id_organizacion"),
        table_name="usuarios_roles_empresa",
    )
    op.drop_index(
        op.f("ix_usuarios_roles_empresa_id_usuario"),
        table_name="usuarios_roles_empresa",
    )
    op.drop_table("usuarios_roles_empresa")

    op.drop_index(
        "uq_rol_empresa_permiso",
        table_name="roles_empresa_permisos",
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )
    op.drop_index(
        op.f("ix_roles_empresa_permisos_id_permiso"),
        table_name="roles_empresa_permisos",
    )
    op.drop_index(
        op.f("ix_roles_empresa_permisos_id_rol_empresa"),
        table_name="roles_empresa_permisos",
    )
    op.drop_table("roles_empresa_permisos")

    op.drop_index(
        "uq_rol_empresa_organizacion_nombre",
        table_name="roles_empresa",
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )
    op.drop_index(op.f("ix_roles_empresa_id_organizacion"), table_name="roles_empresa")
    op.drop_table("roles_empresa")
