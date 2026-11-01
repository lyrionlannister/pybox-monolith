import uuid

import pytest

from identity.organizations.enums.organization_enums import VerificationStatus
from identity.users.enums.user_enums import UserRole, UserScope
from identity.users.schemas.user_session_schema import OrgSessionEntry
from receivables.debtors.enums.debtor_enums import DebtorType

BASE = "/api/v1/databases"

# Nota: `POST /` (create_database) ejecuta CREATE DATABASE real, fuera de cualquier
# transacción, y quedaría persistente en el Postgres compartido -- no se prueba el
# camino válido (decidido con el usuario), solo 401/403. `create_table`/`alter_table`
# sí se prueban con datos reales: corren contra `template_db_test` (la propia base de
# test) con su propia conexión, así que quedan contenidos aunque no hagan rollback --
# se limpian solos al recrear el schema en la próxima sesión de pytest.


def org_scoped_session(make_user_session_factory):
    org_id = str(uuid.uuid4())
    return make_user_session_factory(
        role=UserRole.USER,
        scope=UserScope.ORGANIZATION,
        orgs={
            org_id: OrgSessionEntry(
                role=UserRole.USER,
                org_name="Org",
                verification_status=VerificationStatus.APPROVED,
            )
        },
    )


class TestListSchemas:
    async def test_valid_as_global_admin(self, auth_as, make_user_session_factory):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.get(f"{BASE}/schemas")
        assert resp.status_code == 200
        assert "public" in resp.json()

    async def test_without_global_admin_returns_403(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.get(f"{BASE}/schemas")
        assert resp.status_code == 403

    async def test_without_auth_returns_401(self, client):
        resp = await client.get(f"{BASE}/schemas")
        assert resp.status_code == 401


class TestListTables:
    async def test_valid_as_global_admin(self, auth_as, make_user_session_factory):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.get(f"{BASE}/schemas/public/tables")
        assert resp.status_code == 200
        assert "usuarios" in resp.json()

    async def test_without_global_admin_returns_403(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.get(f"{BASE}/schemas/public/tables")
        assert resp.status_code == 403


class TestListTableFields:
    async def test_valid_as_global_admin(self, auth_as, make_user_session_factory):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.get(f"{BASE}/schemas/public/tables/paises/fields")
        assert resp.status_code == 200
        assert any(f["name"] == "codigo" for f in resp.json())

    async def test_valid_as_org_scoped_user_on_catalog_table(
        self, auth_as, make_user_session_factory
    ):
        """Org-scoped solo puede inspeccionar tablas de TENANT_SCOPED_TABLES (las
        que reports/segments pueden consultar), no cualquier tabla de la base."""
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.get(f"{BASE}/schemas/public/tables/creditos/fields")
        assert resp.status_code == 200
        assert any(f["name"] == "id" for f in resp.json())

    async def test_org_scoped_user_outside_catalog_returns_404(
        self, auth_as, make_user_session_factory
    ):
        """`paises` no está en TENANT_SCOPED_TABLES: aunque exista, un org-scoped no
        puede usar este endpoint para inspeccionar esquema fuera del catálogo."""
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.get(f"{BASE}/schemas/public/tables/paises/fields")
        assert resp.status_code == 404

    async def test_without_org_or_global_returns_403(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.USER, scope=UserScope.SELF)
        )
        resp = await authed.get(f"{BASE}/schemas/public/tables/paises/fields")
        assert resp.status_code == 403

    async def test_enum_column_exposes_values_in_declaration_order(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.get(f"{BASE}/schemas/public/tables/deudores/fields")
        assert resp.status_code == 200
        fields = {f["name"]: f for f in resp.json()}
        assert fields["tipo_deudor"]["type"] == "USER-DEFINED"
        assert fields["tipo_deudor"]["enumValues"] == [m.value for m in DebtorType]

    async def test_non_enum_column_has_null_enum_values(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.get(f"{BASE}/schemas/public/tables/deudores/fields")
        fields = {f["name"]: f for f in resp.json()}
        assert fields["nombre_completo"]["enumValues"] is None
        assert fields["id"]["enumValues"] is None


class TestExecuteQuery:
    async def test_valid_as_global_admin(self, auth_as, make_user_session_factory):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.post(
            f"{BASE}/query",
            json={"tables": [{"name": "paises", "columns": ["codigo", "nombre"]}]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["rows"] >= 5

    async def test_without_global_admin_returns_403(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.post(
            f"{BASE}/query",
            json={"tables": [{"name": "paises", "columns": ["codigo"]}]},
        )
        assert resp.status_code == 403

    async def test_without_auth_returns_401(self, client):
        resp = await client.post(
            f"{BASE}/query",
            json={"tables": [{"name": "paises", "columns": ["codigo"]}]},
        )
        assert resp.status_code == 401


class TestCreateTable:
    async def test_valid_as_global_admin(self, auth_as, make_user_session_factory):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        table_name = f"test_ddl_{uuid.uuid4().hex}"
        resp = await authed.post(
            f"{BASE}/schemas/public/tables",
            json={
                "table_name": table_name,
                "columns": [
                    {
                        "name": "id",
                        "data_type": "INTEGER",
                        "primary_key": True,
                        "nullable": False,
                    },
                    {"name": "label", "data_type": "TEXT"},
                ],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True

        # Confirma que la tabla existe de verdad, vía el endpoint de inspección.
        listing = await authed.get(f"{BASE}/schemas/public/tables")
        assert table_name in listing.json()

    async def test_invalid_identifier_returns_400(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.post(
            f"{BASE}/schemas/public/tables",
            json={
                "table_name": "not a valid ident!",
                "columns": [{"name": "id", "data_type": "INTEGER"}],
            },
        )
        assert resp.status_code == 400

    async def test_without_global_admin_returns_403(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.post(
            f"{BASE}/schemas/public/tables",
            json={
                "table_name": f"test_ddl_{uuid.uuid4().hex}",
                "columns": [{"name": "id", "data_type": "INTEGER"}],
            },
        )
        assert resp.status_code == 403


class TestAlterTable:
    @pytest.fixture
    async def real_table(self, auth_as, make_user_session_factory):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        table_name = f"test_ddl_{uuid.uuid4().hex}"
        create = await authed.post(
            f"{BASE}/schemas/public/tables",
            json={
                "table_name": table_name,
                "columns": [{"name": "id", "data_type": "INTEGER"}],
            },
        )
        assert create.status_code == 201
        return table_name

    async def test_add_column_valid(
        self, real_table, auth_as, make_user_session_factory
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.patch(
            f"{BASE}/schemas/public/tables/{real_table}",
            json={
                "action": "ADD_COLUMN",
                "column": {"name": "extra", "data_type": "TEXT"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        fields = await authed.get(f"{BASE}/schemas/public/tables/{real_table}/fields")
        assert any(f["name"] == "extra" for f in fields.json())

    async def test_add_column_missing_definition_returns_success_false(
        self, real_table, auth_as, make_user_session_factory
    ):
        authed = auth_as(
            make_user_session_factory(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        )
        resp = await authed.patch(
            f"{BASE}/schemas/public/tables/{real_table}",
            json={"action": "ADD_COLUMN"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    async def test_without_global_admin_returns_403(
        self, real_table, auth_as, make_user_session_factory
    ):
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.patch(
            f"{BASE}/schemas/public/tables/{real_table}",
            json={
                "action": "ADD_COLUMN",
                "column": {"name": "extra", "data_type": "TEXT"},
            },
        )
        assert resp.status_code == 403


class TestCreateDatabase:
    async def test_without_global_admin_returns_403(
        self, auth_as, make_user_session_factory
    ):
        authed = auth_as(org_scoped_session(make_user_session_factory))
        resp = await authed.post(
            f"{BASE}/", json={"database_name": f"test_db_{uuid.uuid4().hex}"}
        )
        assert resp.status_code == 403

    async def test_without_auth_returns_401(self, client):
        resp = await client.post(f"{BASE}/", json={"database_name": "whatever"})
        assert resp.status_code == 401
