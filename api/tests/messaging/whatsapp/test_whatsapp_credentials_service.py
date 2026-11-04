"""Tests unitarios de WhatsAppCredentialsService (ver whatsapp_credentials_service.py).

Repo mockeado. Cubre `get` (404 sin configurar), y `upsert` en sus dos ramas:
actualizar una fila existente vs. crear la primera.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from identity.users.enums.user_enums import UserRole, UserScope
from messaging.whatsapp.models.whatsapp_org_credentials_model import (
    WhatsAppOrgCredentialsModel,
)
from messaging.whatsapp.schemas.whatsapp_credentials_schemas import (
    WhatsAppOrgCredentialsRequest,
)
from messaging.whatsapp.services.whatsapp_credentials_service import (
    WhatsAppCredentialsService,
)
from identity.users.schemas.user_session_schema import OrgSessionEntry
from tests.conftest import make_user_session

ADMIN_SESSION = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)


def build_service() -> tuple[WhatsAppCredentialsService, MagicMock]:
    repo = MagicMock()
    repo.get_by_phone_number_id = AsyncMock(return_value=None)
    return WhatsAppCredentialsService(repo), repo


class TestGet:
    async def test_returns_existing_credentials(self):
        organization_id = uuid.uuid4()
        credentials = WhatsAppOrgCredentialsModel(
            organization_id=organization_id, phone_number_id="123"
        )
        service, repo = build_service()
        repo.get_by_organization = AsyncMock(return_value=credentials)

        result = await service.get(organization_id, ADMIN_SESSION)

        assert result is credentials

    async def test_missing_credentials_raise_404(self):
        service, repo = build_service()
        repo.get_by_organization = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await service.get(uuid.uuid4(), ADMIN_SESSION)
        assert exc_info.value.status_code == 404

    async def test_requires_org_admin(self):
        service, repo = build_service()
        agent_session = make_user_session(
            role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.get(uuid.uuid4(), agent_session)
        assert exc_info.value.status_code == 403
        repo.get_by_organization.assert_not_called()


class TestUpsert:
    async def test_creates_new_row_when_none_exists(self):
        organization_id = uuid.uuid4()
        service, repo = build_service()
        repo.get_by_organization = AsyncMock(return_value=None)
        repo.add = AsyncMock(side_effect=lambda m: m)
        data = WhatsAppOrgCredentialsRequest(
            phone_number_id="123456", display_name="Cobranza", active=True
        )

        result = await service.upsert(organization_id, data, ADMIN_SESSION)

        assert result.phone_number_id == "123456"
        assert result.organization_id == organization_id
        repo.update.assert_not_called()

    async def test_updates_existing_row_in_place(self):
        organization_id = uuid.uuid4()
        existing = WhatsAppOrgCredentialsModel(
            organization_id=organization_id,
            phone_number_id="old",
            display_name="Antes",
            active=False,
        )
        service, repo = build_service()
        repo.get_by_organization = AsyncMock(return_value=existing)
        repo.update = AsyncMock(side_effect=lambda m: m)
        data = WhatsAppOrgCredentialsRequest(
            phone_number_id="new-id", display_name="Ahora", active=True
        )

        result = await service.upsert(organization_id, data, ADMIN_SESSION)

        assert result is existing
        assert result.phone_number_id == "new-id"
        assert result.display_name == "Ahora"
        assert result.active is True
        repo.add.assert_not_called()

    async def test_requires_org_admin(self):
        service, repo = build_service()
        agent_session = make_user_session(
            role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
        )
        data = WhatsAppOrgCredentialsRequest(phone_number_id="123")

        with pytest.raises(HTTPException) as exc_info:
            await service.upsert(uuid.uuid4(), data, agent_session)
        assert exc_info.value.status_code == 403

    async def test_org_admin_cannot_assign_numbers(self):
        organization_id = uuid.uuid4()
        service, _repo = build_service()
        org_admin = make_user_session(
            role=None,
            scope=UserScope.ORGANIZATION,
            orgs={
                str(organization_id): OrgSessionEntry(
                    role=UserRole.ADMIN, org_name="Org"
                )
            },
        )
        data = WhatsAppOrgCredentialsRequest(phone_number_id="123")

        with pytest.raises(HTTPException) as exc_info:
            await service.upsert(organization_id, data, org_admin)
        assert exc_info.value.status_code == 403

    async def test_number_of_another_org_returns_409(self):
        service, repo = build_service()
        repo.get_by_phone_number_id = AsyncMock(
            return_value=WhatsAppOrgCredentialsModel(
                organization_id=uuid.uuid4(), phone_number_id="123", active=True
            )
        )
        data = WhatsAppOrgCredentialsRequest(phone_number_id="123")

        with pytest.raises(HTTPException) as exc_info:
            await service.upsert(uuid.uuid4(), data, ADMIN_SESSION)
        assert exc_info.value.status_code == 409
