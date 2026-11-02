"""Configuración de Alembic: arma el motor async y expone target_metadata.

`alembic.context` es un proxy que Alembic puebla en tiempo de ejecución (el
objeto real depende de si se invocó offline u online), por lo que pylint no
puede resolver sus miembros estáticamente.

`alembic_postgresql_enum` y `core.config.models` se importan solo por su
efecto lateral, no se usan directamente: el primero registra los
comparadores de ENUM que Alembic no trae de fábrica (sin esto, agregar un
miembro a un enum de Python produce un diff vacío y el fallo aparece recién
en runtime al insertar el valor nuevo); el segundo registra todos los
modelos en `Base.metadata` para que `--autogenerate` los detecte.
"""

# pylint: disable=no-member

import asyncio
import os
import sys
from logging.config import fileConfig

import alembic_postgresql_enum  # pylint: disable=unused-import
from dotenv import load_dotenv
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Añadir src/ al path para que los imports de los modelos funcionen
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

load_dotenv()

import core.config.models  # pylint: disable=wrong-import-position,unused-import
from core.config.database_config import (  # pylint: disable=wrong-import-position
    db_config,
)
from core.database.database import Base  # pylint: disable=wrong-import-position

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def migration_url() -> str:
    """URL de conexión para migrar — Postgres directo, no pgbouncer.

    La API habla con la base a través de pgbouncer en modo `transaction`, donde el
    pooler devuelve la conexión al pool al cerrar cada transacción. Ahí las
    migraciones no funcionan: `CREATE INDEX CONCURRENTLY` y cualquier
    `autocommit_block()` necesitan una sesión propia y estable.
    ALEMBIC_DB_HOST/ALEMBIC_DB_PORT apuntan al Postgres real; si no están
    definidas se usa la conexión normal de la app.
    """
    host = os.getenv("ALEMBIC_DB_HOST") or db_config.host
    port = os.getenv("ALEMBIC_DB_PORT") or db_config.port
    url = URL.create(
        drivername=f"{db_config.database_engine}+{db_config.database_driver}",
        username=db_config.username,
        password=db_config.password,
        host=host,
        port=int(port),
        database=db_config.database_name,
    )
    return url.render_as_string(hide_password=False)


def _skip_empty_revision(context_, _revision, directives) -> None:
    """Evita revisiones vacías cuando `--autogenerate` no encontró nada que cambiar.

    Sin esto, un autogenerate sin cambios genera igual un archivo con `pass` en
    upgrade y downgrade, y esos archivos se acumulan en la historia sin decir nada.
    """
    if (
        getattr(context_.config.cmd_opts, "autogenerate", False)
        and directives[0].upgrade_ops.is_empty()
    ):
        directives[:] = []
        print("Sin cambios en los modelos: no se genera revisión.")


# compare_type: detecta cambios de tipo de columna (p. ej. Double -> Numeric).
# compare_server_default: detecta cambios de DEFAULT del lado de Postgres. Ojo,
# ninguno de los dos ve renombres — un rename siempre se autogenera como drop +
# add, y eso borra datos: hay que reescribirlo a mano como
# `op.alter_column(..., new_column_name=)`.
_CONTEXT_OPTS = {
    "target_metadata": target_metadata,
    "compare_type": True,
    "compare_server_default": True,
    "process_revision_directives": _skip_empty_revision,
}


def run_migrations_offline() -> None:
    context.configure(
        url=migration_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_CONTEXT_OPTS,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, **_CONTEXT_OPTS)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(migration_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
