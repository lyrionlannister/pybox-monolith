"""Tests unitarios de WhatsAppChatService (ver whatsapp_chat_service.py).

Todo mockeado (repos + cliente Meta) -- no toca la base de datos real. Cubre el
alcance de visibilidad por rol (admin de la organización ve todo, agente solo lo
asignado + su portafolio), la ventana de servicio al cliente de 24h para texto
libre, y el armado de WhatsAppChatDetailsResponse con sus ramas de deudor/
portafolio/campaña ausentes.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from identity.users.enums.user_enums import UserRole, UserScope
from messaging.whatsapp.enums.whatsapp_enums import MessageDirection
from messaging.whatsapp.models.whatsapp_chat_model import WhatsAppChatModel
from messaging.whatsapp.models.whatsapp_message_model import WhatsAppMessageModel
from messaging.whatsapp.services.whatsapp_chat_service import WhatsAppChatService
from tests.conftest import make_user_session


def build_service(**overrides) -> tuple[WhatsAppChatService, dict]:
    mocks = dict(
        chat_repo=MagicMock(),
        message_repo=MagicMock(),
        portfolio_access_repo=MagicMock(),
        credentials_repo=MagicMock(),
        client=MagicMock(),
        debtor_repo=MagicMock(),
        credit_repo=MagicMock(),
        portfolio_repo=MagicMock(),
        campaign_repo=MagicMock(),
        user_repo=MagicMock(),
        org_repo=MagicMock(),
        membership_repo=MagicMock(),
    )
    mocks.update(overrides)
    mocks["portfolio_repo"].session = MagicMock()
    service = WhatsAppChatService(**mocks)
    # `_country_repo`/`_credential_service` se instancian dentro de __init__ contra
    # `portfolio_repo.session` -- se parchan directo para no requerir sesión real.
    service._country_repo = MagicMock()
    service._credential_service = MagicMock()
    return service, mocks


class TestGetChatForUser:
    async def test_admin_can_access_any_assigned_chat(self):
        organization_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            assigned_user_id=uuid.uuid4(),
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        result = await service._get_chat_for_user(chat.id, organization_id, session)

        assert result is chat
        mocks["portfolio_access_repo"].check_active_access.assert_not_called()

    async def test_chat_not_found_raises_404(self):
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=None)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        with pytest.raises(HTTPException) as exc_info:
            await service._get_chat_for_user(uuid.uuid4(), uuid.uuid4(), session)
        assert exc_info.value.status_code == 404

    async def test_chat_from_different_organization_raises_404(self):
        chat = WhatsAppChatModel(
            id=uuid.uuid4(), organization_id=uuid.uuid4(), phone="573000000000"
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        with pytest.raises(HTTPException) as exc_info:
            await service._get_chat_for_user(chat.id, uuid.uuid4(), session)
        assert exc_info.value.status_code == 404

    async def test_agent_not_assigned_to_chat_raises_403(self):
        organization_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        other_agent_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            assigned_user_id=other_agent_id,
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        session = make_user_session(
            user_id=agent_id, role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
        )

        with pytest.raises(HTTPException) as exc_info:
            await service._get_chat_for_user(chat.id, organization_id, session)
        assert exc_info.value.status_code == 403

    async def test_agent_assigned_without_portfolio_access_raises_403(self):
        organization_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            assigned_user_id=agent_id,
            portfolio_id=portfolio_id,
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["portfolio_access_repo"].check_active_access = AsyncMock(
            return_value=False
        )
        session = make_user_session(
            user_id=agent_id, role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
        )

        with pytest.raises(HTTPException) as exc_info:
            await service._get_chat_for_user(chat.id, organization_id, session)
        assert exc_info.value.status_code == 403

    async def test_agent_assigned_chat_without_portfolio_raises_403(self):
        """Sin portafolio resuelto en el hilo, un agente no-admin nunca tiene acceso
        (solo admins ven hilos huérfanos) -- ver comentario en whatsapp_assignment_service.
        """
        organization_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            assigned_user_id=agent_id,
            portfolio_id=None,
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        session = make_user_session(
            user_id=agent_id, role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
        )

        with pytest.raises(HTTPException) as exc_info:
            await service._get_chat_for_user(chat.id, organization_id, session)
        assert exc_info.value.status_code == 403
        mocks["portfolio_access_repo"].check_active_access.assert_not_called()

    async def test_agent_assigned_with_portfolio_access_succeeds(self):
        organization_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            assigned_user_id=agent_id,
            portfolio_id=portfolio_id,
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["portfolio_access_repo"].check_active_access = AsyncMock(
            return_value=True
        )
        session = make_user_session(
            user_id=agent_id, role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
        )

        result = await service._get_chat_for_user(chat.id, organization_id, session)
        assert result is chat


class TestListChats:
    async def test_specific_org_uses_single_scope(self):
        organization_id = uuid.uuid4()
        service, mocks = build_service()
        mocks["chat_repo"].list_by_scopes = AsyncMock(return_value=([], 0))
        mocks["org_repo"].get_by_ids = AsyncMock(return_value=[])
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        items, total = await service.list_chats(1, 20, session, organization_id)

        assert items == []
        assert total == 0
        call_args = mocks["chat_repo"].list_by_scopes.call_args
        scopes, page, page_size, unrestricted = call_args.args
        assert len(scopes) == 1
        assert scopes[0].organization_id == organization_id
        assert unrestricted is False

    async def test_global_user_without_org_filter_is_unrestricted(self):
        service, mocks = build_service()
        mocks["chat_repo"].list_by_scopes = AsyncMock(return_value=([], 0))
        mocks["org_repo"].get_by_ids = AsyncMock(return_value=[])
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        await service.list_chats(1, 20, session, None)

        scopes, _page, _page_size, unrestricted = mocks[
            "chat_repo"
        ].list_by_scopes.call_args.args
        assert scopes == []
        assert unrestricted is True

    async def test_org_user_without_org_filter_scopes_by_permitted_orgs_only(self):
        from identity.users.schemas.user_session_schema import OrgSessionEntry

        org_with_perm = uuid.uuid4()
        org_without_perm = uuid.uuid4()
        service, mocks = build_service()
        mocks["chat_repo"].list_by_scopes = AsyncMock(return_value=([], 0))
        mocks["portfolio_access_repo"].get_active_by_user_and_org = AsyncMock(
            return_value=[]
        )
        mocks["org_repo"].get_by_ids = AsyncMock(return_value=[])
        session = make_user_session(
            role=UserRole.USER,
            scope=UserScope.ORGANIZATION,
            orgs={
                str(org_with_perm): OrgSessionEntry(
                    role=UserRole.USER,
                    org_name="A",
                    permissions=frozenset({"org.manage_whatsapp_chats"}),
                ),
                str(org_without_perm): OrgSessionEntry(
                    role=UserRole.USER, org_name="B", permissions=frozenset()
                ),
            },
        )

        await service.list_chats(1, 20, session, None)

        scopes, _page, _page_size, unrestricted = mocks[
            "chat_repo"
        ].list_by_scopes.call_args.args
        assert unrestricted is False
        assert len(scopes) == 1
        assert scopes[0].organization_id == org_with_perm

    async def test_response_includes_organization_name(self):
        organization_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            created_at=datetime.now(timezone.utc),
        )
        service, mocks = build_service()
        mocks["chat_repo"].list_by_scopes = AsyncMock(return_value=([chat], 1))
        org = MagicMock(id=organization_id)
        org.name = "Cobranzas SA"
        mocks["org_repo"].get_by_ids = AsyncMock(return_value=[org])
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        items, total = await service.list_chats(1, 20, session, organization_id)

        assert total == 1
        assert items[0].organization_name == "Cobranzas SA"


class TestAssign:
    async def test_assign_updates_chat_and_returns_it(self):
        organization_id = uuid.uuid4()
        new_agent_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(), organization_id=organization_id, phone="573000000000"
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["chat_repo"].update = AsyncMock(side_effect=lambda c: c)
        mocks["membership_repo"].get_by_user_id = AsyncMock(
            return_value=[MagicMock(organization_id=organization_id)]
        )
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        result = await service.assign(chat.id, organization_id, new_agent_id, session)

        assert result.assigned_user_id == new_agent_id
        mocks["chat_repo"].update.assert_awaited_once()

    async def test_assign_chat_not_found_raises_404(self):
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=None)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        with pytest.raises(HTTPException) as exc_info:
            await service.assign(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), session)
        assert exc_info.value.status_code == 404

    async def test_assign_rejects_user_outside_organization(self):
        organization_id = uuid.uuid4()
        other_org_id = uuid.uuid4()
        new_agent_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(), organization_id=organization_id, phone="573000000000"
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["membership_repo"].get_by_user_id = AsyncMock(
            return_value=[MagicMock(organization_id=other_org_id)]
        )
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        with pytest.raises(HTTPException) as exc_info:
            await service.assign(chat.id, organization_id, new_agent_id, session)
        assert exc_info.value.status_code == 422
        mocks["chat_repo"].update.assert_not_called()

    async def test_assign_requires_org_admin(self):
        organization_id = uuid.uuid4()
        service, _mocks = build_service()
        session = make_user_session(
            role=UserRole.USER, scope=UserScope.ORGANIZATION, orgs={}
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.assign(uuid.uuid4(), organization_id, uuid.uuid4(), session)
        assert exc_info.value.status_code == 403


class TestSendMessage:
    def _make_chat(self, organization_id, chat_id=None) -> WhatsAppChatModel:
        return WhatsAppChatModel(
            id=chat_id or uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
        )

    async def test_no_inbound_message_ever_blocks_send_with_409(self):
        organization_id = uuid.uuid4()
        chat = self._make_chat(organization_id)
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["message_repo"].get_last_inbound = AsyncMock(return_value=None)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        with pytest.raises(HTTPException) as exc_info:
            await service.send_message(chat.id, organization_id, "hola", session)
        assert exc_info.value.status_code == 409

    async def test_inbound_older_than_24h_blocks_send_with_409(self):
        organization_id = uuid.uuid4()
        chat = self._make_chat(organization_id)
        stale_inbound = WhatsAppMessageModel(
            id=uuid.uuid4(),
            chat_id=chat.id,
            direction=MessageDirection.INBOUND,
            message_type="text",
            content="hola",
            raw_payload={},
            sent_at=datetime.now(timezone.utc) - timedelta(hours=25),
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["message_repo"].get_last_inbound = AsyncMock(return_value=stale_inbound)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        with pytest.raises(HTTPException) as exc_info:
            await service.send_message(chat.id, organization_id, "hola", session)
        assert exc_info.value.status_code == 409

    async def test_no_credentials_configured_returns_409(self):
        organization_id = uuid.uuid4()
        chat = self._make_chat(organization_id)
        recent_inbound = WhatsAppMessageModel(
            id=uuid.uuid4(),
            chat_id=chat.id,
            direction=MessageDirection.INBOUND,
            message_type="text",
            content="hola",
            raw_payload={},
            sent_at=datetime.now(timezone.utc),
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["message_repo"].get_last_inbound = AsyncMock(return_value=recent_inbound)
        mocks["credentials_repo"].get_by_organization = AsyncMock(return_value=None)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        with pytest.raises(HTTPException) as exc_info:
            await service.send_message(chat.id, organization_id, "hola", session)
        assert exc_info.value.status_code == 409

    async def test_client_send_failure_returns_502(self):
        organization_id = uuid.uuid4()
        chat = self._make_chat(organization_id)
        recent_inbound = WhatsAppMessageModel(
            id=uuid.uuid4(),
            chat_id=chat.id,
            direction=MessageDirection.INBOUND,
            message_type="text",
            content="hola",
            raw_payload={},
            sent_at=datetime.now(timezone.utc),
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["message_repo"].get_last_inbound = AsyncMock(return_value=recent_inbound)
        mocks["credentials_repo"].get_by_organization = AsyncMock(
            return_value=MagicMock(phone_number_id="123")
        )
        mocks["client"].send_text = AsyncMock(return_value=(False, None))
        service._credential_service.get_decrypted = AsyncMock(return_value=None)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        with pytest.raises(HTTPException) as exc_info:
            await service.send_message(chat.id, organization_id, "hola", session)
        assert exc_info.value.status_code == 502

    async def test_successful_send_persists_outbound_message_and_updates_chat(self):
        organization_id = uuid.uuid4()
        chat = self._make_chat(organization_id)
        recent_inbound = WhatsAppMessageModel(
            id=uuid.uuid4(),
            chat_id=chat.id,
            direction=MessageDirection.INBOUND,
            message_type="text",
            content="hola",
            raw_payload={},
            sent_at=datetime.now(timezone.utc),
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["message_repo"].get_last_inbound = AsyncMock(return_value=recent_inbound)
        mocks["credentials_repo"].get_by_organization = AsyncMock(
            return_value=MagicMock(phone_number_id="123")
        )
        mocks["client"].send_text = AsyncMock(return_value=(True, "wamid.out1"))
        mocks["message_repo"].add = AsyncMock(side_effect=lambda m: m)
        mocks["chat_repo"].update = AsyncMock(side_effect=lambda c: c)
        service._credential_service.get_decrypted = AsyncMock(
            return_value={"access_token": "tok"}
        )
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        message = await service.send_message(
            chat.id, organization_id, "hola de vuelta", session
        )

        assert message.direction == MessageDirection.OUTBOUND
        assert message.wamid == "wamid.out1"
        assert message.content == "hola de vuelta"
        mocks["client"].send_text.assert_awaited_once_with(
            "123", chat.phone, "hola de vuelta", token="tok"
        )
        assert chat.last_message_at is not None
        mocks["chat_repo"].update.assert_awaited_once()


class TestGetChatDetails:
    async def test_chat_without_debtor_or_portfolio_or_campaign(self):
        organization_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(), organization_id=organization_id, phone="573000000000"
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        result = await service.get_chat_details(chat.id, organization_id, session)

        assert result.debtor is None
        assert result.is_self_registered is False
        assert result.portfolio is None
        assert result.campaign is None
        assert result.credits == []

    async def test_chat_with_debtor_and_portfolio_includes_credits_and_self_registration(
        self,
    ):
        organization_id = uuid.uuid4()
        debtor_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            debtor_id=debtor_id,
            portfolio_id=portfolio_id,
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)

        debtor = MagicMock(
            id=debtor_id,
            full_name="Juan Deudor",
            debtor_type="TITULAR",
            document_type="CC",
            document_number=b"enc",
        )
        mocks["debtor_repo"].get_by_id = AsyncMock(return_value=debtor)
        mocks["user_repo"].get_by_document = AsyncMock(
            return_value=MagicMock()
        )  # existe cuenta propia

        portfolio = MagicMock(id=portfolio_id)
        portfolio.name = "Portafolio Q1"
        mocks["portfolio_repo"].get_by_id = AsyncMock(return_value=portfolio)
        service._country_repo.get_currency_code = AsyncMock(return_value="COP")

        credit = MagicMock(
            id=uuid.uuid4(),
            credit_number="CR-1",
            credit_type="CREDITO_CONSUMO",
            disbursed_date=datetime.now(timezone.utc),
            total_credit_balance=1000,
            overdue_principal_balance=200,
            days_overdue_at_cutoff=30,
            overdue_installments=1,
            pending_installments=5,
        )
        mocks["credit_repo"].get_by_debtor_and_portfolio = AsyncMock(
            return_value=[credit]
        )

        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)
        with patch(
            "messaging.whatsapp.services.whatsapp_chat_service.encrypt_service"
        ) as mock_encrypt:
            mock_encrypt.decrypt_to_str.return_value = "123456789"
            result = await service.get_chat_details(chat.id, organization_id, session)

        assert result.debtor is not None
        assert result.debtor.document_number == "123456789"
        assert result.is_self_registered is True
        assert result.portfolio.name == "Portafolio Q1"
        assert len(result.credits) == 1
        assert result.credits[0].currency_code == "COP"

    async def test_debtor_id_set_but_debtor_missing_is_tolerated(self):
        organization_id = uuid.uuid4()
        debtor_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            debtor_id=debtor_id,
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["debtor_repo"].get_by_id = AsyncMock(return_value=None)
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        result = await service.get_chat_details(chat.id, organization_id, session)

        assert result.debtor is None
        assert result.is_self_registered is False

    async def test_campaign_id_set_and_found_includes_campaign_info(self):
        organization_id = uuid.uuid4()
        campaign_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            campaign_id=campaign_id,
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        from messaging.campaigns.enums.campaign_enums import CampaignStatus

        campaign = MagicMock(id=campaign_id, status=CampaignStatus.RUNNING)
        campaign.name = "Campaña Julio"
        mocks["campaign_repo"].get_by_id_and_organization_id = AsyncMock(
            return_value=campaign
        )
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        result = await service.get_chat_details(chat.id, organization_id, session)

        assert result.campaign is not None
        assert result.campaign.name == "Campaña Julio"

    async def test_campaign_id_set_but_not_found_is_tolerated(self):
        organization_id = uuid.uuid4()
        campaign_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(),
            organization_id=organization_id,
            phone="573000000000",
            campaign_id=campaign_id,
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["campaign_repo"].get_by_id_and_organization_id = AsyncMock(
            return_value=None
        )
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        result = await service.get_chat_details(chat.id, organization_id, session)

        assert result.campaign is None


class TestListMessages:
    async def test_lists_messages_for_accessible_chat(self):
        organization_id = uuid.uuid4()
        chat = WhatsAppChatModel(
            id=uuid.uuid4(), organization_id=organization_id, phone="573000000000"
        )
        message = WhatsAppMessageModel(
            id=uuid.uuid4(),
            chat_id=chat.id,
            direction=MessageDirection.INBOUND,
            message_type="text",
            content="hola",
            raw_payload={},
            sent_at=datetime.now(timezone.utc),
        )
        service, mocks = build_service()
        mocks["chat_repo"].get_by_id = AsyncMock(return_value=chat)
        mocks["message_repo"].list_by_chat = AsyncMock(return_value=[message])
        session = make_user_session(role=UserRole.ADMIN, scope=UserScope.GLOBAL)

        messages = await service.list_messages(chat.id, organization_id, session)

        assert messages == [message]
        mocks["message_repo"].list_by_chat.assert_awaited_once_with(chat.id)
