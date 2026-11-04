import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Callable

# Debe ejecutarse antes de cualquier import de `src`: `core.config.database_config`
# lee las env vars a nivel de módulo (import time), así que si `DB_NAME` no está
# pisada para acá, apuntaría a la base de datos de desarrollo real.
os.environ.setdefault("DB_NAME", "template_db_test")
# `.env` trae DB_HOST=database (hostname interno de podman, solo resuelve entre
# containers) -- desde el host hay que hablarle al puerto publicado.
os.environ.setdefault("DB_HOST", "127.0.0.1")
# `STORAGE_ENDPOINT` solo está definido en docker-compose.yaml (hostname interno
# `storage`, no resuelve desde el host) -- deliberadamente NO va en `.env` (ver
# comentario en `.env.example`), así que el import chain `user_service ->
# document_service -> S3ObjectStorage` lo exige al importarse y no lo encuentra.
# `https://storage.pybox.local` (el dominio que usa STORAGE_PUBLIC_ENDPOINT, vía
# nginx) resuelve pero falla la verificación TLS: el cert de nginx es de mkcert,
# boto3/aiobotocore no confía en esa CA local (`SSLCertVerificationError`). Se usa
# el puerto publicado del container directo, sin TLS de por medio -- el 3004 de
# `docker-compose.yaml` (`127.0.0.1:3004:8333`), no el 8333 interno del container.
os.environ.setdefault("STORAGE_ENDPOINT", "http://127.0.0.1:3004")
# Un bucket/colección de test separado ("documentos-test") no funciona: este SeaweedFS
# de un solo nodo no logra crearle volúmenes nuevos ("not enough data nodes", aunque
# sobra disco -- límite del server, no algo para tocar sin autorización). Se reutiliza
# la colección real de dev ("documentos", que sí tiene volúmenes asignados); los objetos
# de test usan `object_key` con UUID aleatorio (ver `tests/factories.py`), así que no
# chocan con datos reales -- solo agregan objetos nuevos, nunca leen ni pisan existentes.
os.environ.setdefault("STORAGE_BUCKET", "documentos")
# `.env` trae COOKIE_DOMAIN=.pybox.co (dominio real de producción, ver memoria de
# entorno) -- el `base_url` de `client`/`ws_client` abajo usa `api.pybox.local` a
# propósito, así que hace falta pisar (no `setdefault`: la var ya viene seteada desde
# `docker-compose.yaml`) para que el navegador de test acepte la cookie `Set-Cookie`
# (dominio no coincide = httpx la descarta en silencio, sin error).
os.environ["COOKIE_DOMAIN"] = ".pybox.local"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import core.config.models
from core.database import redis as redis_module
from core.database.database import Base, db, get_main_session
from core.security.dependencies import (
    get_pending_mfa_session,
    get_session,
    get_sse_session,
    get_ws_session,
)
from core.seed import (
    seed_admin,
    seed_channels,
    seed_countries,
    seed_messaging_credentials,
    seed_permissions,
    seed_platform_gateway_credentials,
)
from identity.auth.dependencies import _get_token_payload
from identity.auth.services.verification_service import VerificationService
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_session_schema import UserSession
from main import app as fastapi_app
from tests.factories import TEST_OTP_CODE


# ---------------------------------------------------------------------------
# Fake Redis: reemplaza el backend interno (`redis_client._client`) del
# singleton compartido por sesiones, rate limiting y logout/reset. Todo el
# código de la app importa `redis_client` (misma instancia), así que parchar
# su `_client` alcanza sin necesidad de tocar cada import.
# ---------------------------------------------------------------------------
class _FakeAsyncRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, datetime | None]] = {}

    def _expired(self, key: str) -> bool:
        entry = self._store.get(key)
        if entry is None:
            return True
        _, expires_at = entry
        if expires_at is not None and expires_at < datetime.now(timezone.utc):
            del self._store[key]
            return True
        return False

    async def get(self, key: str) -> str | None:
        if self._expired(key):
            return None
        return self._store[key][0]

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ex) if ex else None
        self._store[key] = (value, expires_at)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)

    async def incr(self, key: str) -> int:
        current = 0 if self._expired(key) else int(self._store[key][0])
        current += 1
        _, expires_at = self._store.get(key, (None, None))
        self._store[key] = (str(current), expires_at)
        return current

    async def expire(self, key: str, ttl_seconds: int) -> None:
        if key in self._store and not self._expired(key):
            value, _ = self._store[key]
            self._store[key] = (
                value,
                datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
            )

    async def config_set(self, name: str, value: str) -> None:
        return None

    async def scan_iter(self, match: str | None = None):
        """Soporte mínimo para `RedisClient.delete_by_pattern` (usado por
        `cache_service.bust_prefix`): sin `match` recorre todo, con `match` filtra por
        el mismo patrón glob que Redis (`fnmatch` -- suficiente para los `prefix:*` que
        arma `bust_prefix`)."""
        import fnmatch

        keys = [key for key in self._store if not self._expired(key)]
        for key in keys:
            if match is None or fnmatch.fnmatch(key, match):
                yield key

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def deterministic_otp(monkeypatch):
    """Los OTP se guardan hasheados: los tests conocen el código por esta vía."""
    monkeypatch.setattr(
        VerificationService, "_generate_code", lambda self: TEST_OTP_CODE
    )


@pytest_asyncio.fixture(autouse=True)
async def fake_redis() -> AsyncGenerator[_FakeAsyncRedis, None]:
    """Instancia nueva por test: evita que los contadores de rate limit o las
    sesiones de un test contaminen el siguiente."""
    fake = _FakeAsyncRedis()
    redis_module.redis_client._client = fake
    yield fake


# ---------------------------------------------------------------------------
# Base de datos de test: esquema recreado una vez por sesión de pytest contra
# `template_db_test` (ver TESTING_ROADMAP.md), con los catálogos base
# sembrados igual que en el lifespan real (menos schedulers/listeners).
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepared_database() -> AsyncGenerator[None, None]:
    from sqlalchemy import text

    async with db.engine.begin() as conn:
        # `Base.metadata.drop_all` no puede ordenar el DROP: hay una dependencia
        # circular de FKs entre documentos/entidades/usuarios y esas constraints
        # no tienen nombre. Recrear el schema completo evita el problema.
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    async with db.get_session() as session:
        await seed_countries(session)
    async with db.get_session() as session:
        await seed_messaging_credentials(session)
    async with db.get_session() as session:
        await seed_platform_gateway_credentials(session)
    async with db.get_session() as session:
        await seed_permissions(session)
    async with db.get_session() as session:
        await seed_admin(session)
    async with db.get_session() as session:
        await seed_channels(session)
    yield
    await db.engine.dispose()


# ---------------------------------------------------------------------------
# Object storage: el lifespan real llama `object_storage.startup()` (crea los
# clientes S3 + asegura el bucket); como el lifespan de test es un no-op, hay
# que inicializarlo a mano. El container `template-storage` (SeaweedFS) ya
# corre y publica su puerto al host, así que esto habla contra el real -- no
# hay fake para storage, solo un bucket de test separado.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session", autouse=True)
async def _object_storage() -> AsyncGenerator[None, None]:
    from core.storage.s3_object_storage import object_storage

    await object_storage.startup()
    yield
    await object_storage.shutdown()


@pytest_asyncio.fixture
async def db_session():
    """Conexión + transacción externa por test, revertida al final: cualquier
    `commit()` del código de la app crea un savepoint en vez de persistir,
    dejando la DB limpia para el siguiente test."""
    async with db.engine.connect() as conn:
        outer_trans = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with session_factory() as session:
            yield session
        await outer_trans.rollback()


# ---------------------------------------------------------------------------
# App / cliente HTTP: se reemplaza el lifespan real (schedulers, listener de
# expiración de Redis, seeding, storage) por uno vacío -- `_prepared_database`
# ya deja el esquema y los catálogos listos.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def _noop_lifespan(_app):
    yield


fastapi_app.router.lifespan_context = _noop_lifespan


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_main_session():
        yield db_session

    fastapi_app.dependency_overrides[get_main_session] = _override_get_main_session

    # Los background tasks (ver receivables/portfolios/background_tasks.py,
    # installment_background_tasks.py, reports/background_tasks.py) abren su PROPIA
    # sesión con `db.get_session()` en vez de recibir la de la request -- así deben
    # comportarse en producción (dependencias `yield` cierran antes de que corran los
    # background tasks). Sin este parche, esa sesión nueva abre OTRA conexión que no
    # ve los datos que este test insertó todavía sin commit en `db_session` (misma
    # transacción externa que se revierte al final del test).
    @asynccontextmanager
    async def _bg_session_override():
        yield db_session

    original_get_session = db.get_session
    db.get_session = _bg_session_override

    transport = ASGITransport(app=fastapi_app)
    # El host tiene que caer bajo COOKIE_DOMAIN (`.pybox.local`) y ser https, si no
    # el cookie jar de httpx descarta las cookies de auth (secure + domain-matched)
    # y el login/refresh/logout end-to-end no puede encadenar requests.
    async with AsyncClient(
        transport=transport, base_url="https://api.pybox.local"
    ) as ac:
        yield ac
    db.get_session = original_get_session
    fastapi_app.dependency_overrides.pop(get_main_session, None)


@pytest.fixture
def ws_client(client: AsyncClient) -> Callable[[], AsyncClient]:
    """Fábrica de clientes para el WebSocket de chats -- `httpx.ASGITransport` normal
    no habla el protocolo de upgrade de WebSocket, hace falta `ASGIWebSocketTransport`
    de `httpx-ws`. Es una fábrica (no un cliente ya abierto) a propósito: el `async
    with` de entrada/salida tiene que pasar DENTRO del cuerpo del test, en la misma
    tarea. Si se abre en el setup de un fixture y se cierra en su teardown -- fases
    que pytest-asyncio corre como tareas separadas aunque compartan el mismo loop de
    sesión -- el `CancelScope` interno de `anyio`/`httpx-ws` revienta con "Attempted
    to exit cancel scope in a different task than it was entered in".
    Depende de `client` para que `get_main_session` ya esté pisado contra la misma
    `db_session` de este test (mismo `fastapi_app` compartido, así que la conexión WS
    ve los mismos datos que ya insertó el test por HTTP)."""
    from httpx_ws.transport import ASGIWebSocketTransport

    def _factory() -> AsyncClient:
        transport = ASGIWebSocketTransport(app=fastapi_app)
        return AsyncClient(transport=transport, base_url="https://api.pybox.local")

    return _factory


# ---------------------------------------------------------------------------
# Auth: construir un UserSession a medida y autenticar `client` con él, sin
# pasar por JWT real ni Redis.
# ---------------------------------------------------------------------------
def make_user_session(
    *,
    user_id: uuid.UUID | None = None,
    role: UserRole | None = UserRole.ADMIN,
    scope: UserScope | None = UserScope.GLOBAL,
    email: str | None = None,
    orgs: dict[str, Any] | None = None,
    **overrides: Any,
) -> UserSession:
    return UserSession(
        user_id=user_id or uuid.uuid4(),
        full_name=overrides.pop("full_name", "Test User"),
        email=email or f"{uuid.uuid4()}@example.com",
        role=role,
        scope=scope,
        orgs=orgs or {},
        **overrides,
    )


@pytest.fixture
def make_user_session_factory() -> Callable[..., UserSession]:
    return make_user_session


@pytest.fixture
def auth_as(client: AsyncClient) -> Callable[[UserSession], AsyncClient]:
    """`auth_as(session)` autentica `client` como `session` para el resto del
    test. Sobreescribe las 4 dependencias de auth (HTTP, SSE, WS) por función,
    no por módulo, así que cubre a todos los routers que las importan."""

    def _clear() -> None:
        for dep in (
            _get_token_payload,
            get_session,
            get_pending_mfa_session,
            get_ws_session,
            get_sse_session,
        ):
            fastapi_app.dependency_overrides.pop(dep, None)

    def _apply(user_session: UserSession) -> AsyncClient:
        async def _payload_override() -> dict[str, Any]:
            return {"sub": str(user_session.user_id), "email": user_session.email}

        async def _session_override() -> UserSession:
            return user_session

        fastapi_app.dependency_overrides[_get_token_payload] = _payload_override
        fastapi_app.dependency_overrides[get_session] = _session_override
        fastapi_app.dependency_overrides[get_pending_mfa_session] = _session_override
        fastapi_app.dependency_overrides[get_ws_session] = _session_override
        fastapi_app.dependency_overrides[get_sse_session] = _session_override
        return client

    # Fixtures de setup que solo necesitan `auth_as` para preparar datos previos
    # (p. ej. crear una org como admin antes de probar un endpoint sin auth) pueden
    # llamar `auth_as.clear()` para no dejar la sesión pegada dentro del mismo test.
    _apply.clear = _clear
    yield _apply
    _clear()
