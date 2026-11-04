"""Tests de `TemplateService` (CRUD + preview de plantillas, ver template_service.py).
Riesgos reales: `update` con `exclude_unset` no debe pisar campos que el caller no
mandó (un PATCH parcial no debe borrar el resto de la plantilla), `get_by_id` es la
puerta de acceso reutilizada por todos los demás métodos (404 si no existe, además del
chequeo de organización), y `preview` debe reportar las variables detectadas en
cuerpo+asunto aunque el `sub` no traiga valor para todas.

Unitarios puros: `TemplateRepository`/`PortfolioRepository` van mockeados; el
`check_portfolio_org_access` real corre contra un `PortfolioModel` en memoria (no una
sesión), así que no hace falta mockearlo aparte.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from messaging.templates.enums.template_enums import TemplateStatus
from messaging.templates.schemas.template_schemas import (
    TemplateCreateRequest,
    TemplatePreviewRequest,
    TemplateSendRequest,
    TemplateUpdateRequest,
)
from messaging.templates.services.template_service import TemplateService
from messaging.channels.enums.channel_enums import ChannelName


def build_service():
    template_repo = MagicMock()
    portfolio_repo = MagicMock()
    service = TemplateService(template_repo, portfolio_repo)
    return service, template_repo, portfolio_repo


def make_user_session(*, is_global=True, email="usuario@example.com"):
    session = MagicMock()
    session.is_global = is_global
    session.email = email
    session.user_id = uuid.uuid4()
    return session


def make_portfolio(organization_id=None, country="CO"):
    portfolio = MagicMock()
    portfolio.organization_id = organization_id or uuid.uuid4()
    portfolio.country = country
    return portfolio


class TestGetByIdNotFound:
    async def test_missing_template_raises_404(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        template_repo.get_by_id_and_portfolio = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_by_id(uuid.uuid4(), uuid.uuid4(), make_user_session())

        assert exc_info.value.status_code == 404

    async def test_missing_portfolio_raises_404_before_querying_template(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_by_id(uuid.uuid4(), uuid.uuid4(), make_user_session())

        assert exc_info.value.status_code == 404
        template_repo.get_by_id_and_portfolio.assert_not_called()


class TestCreate:
    async def test_create_persists_all_provided_fields(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_id = uuid.uuid4()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        template_repo.add = AsyncMock(side_effect=lambda t: t)

        data = TemplateCreateRequest(
            name="Recordatorio", channel=ChannelName.SMS, body="Hola {nombre}"
        )
        result = await service.create(portfolio_id, data, make_user_session())

        assert result.name == "Recordatorio"
        assert result.body == "Hola {nombre}"
        assert result.portfolio_id == portfolio_id
        template_repo.add.assert_awaited_once()


class TestUpdate:
    async def test_partial_update_only_overwrites_fields_that_were_set(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        # `name` es un kwarg reservado del constructor de MagicMock (fija el nombre
        # interno del mock, no el atributo) -- se asigna aparte para que quede real.
        existing = MagicMock(
            id=uuid.uuid4(),
            body="cuerpo original",
            subject=None,
            status=TemplateStatus.DRAFT,
        )
        existing.name = "Original"
        template_repo.get_by_id_and_portfolio = AsyncMock(return_value=existing)
        template_repo.update = AsyncMock(side_effect=lambda t: t)

        # Solo `status` va explícito -- `name`/`body` no deben tocarse.
        data = TemplateUpdateRequest(status=TemplateStatus.ACTIVE)
        result = await service.update(
            uuid.uuid4(), uuid.uuid4(), data, make_user_session()
        )

        assert result.status == TemplateStatus.ACTIVE
        assert result.name == "Original"
        assert result.body == "cuerpo original"


class TestDelete:
    async def test_delete_looks_up_before_deleting(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        existing = MagicMock(id=uuid.uuid4())
        template_repo.get_by_id_and_portfolio = AsyncMock(return_value=existing)
        template_repo.delete = AsyncMock()

        await service.delete(uuid.uuid4(), uuid.uuid4(), make_user_session())

        template_repo.delete.assert_awaited_once_with(existing)


class TestPreview:
    async def test_reports_variables_from_body_and_subject_and_renders_available_ones(
        self,
    ):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        template = MagicMock(
            body="Hola {nombre}, saldo {saldo}", subject="Recordatorio {nombre}"
        )
        template_repo.get_by_id_and_portfolio = AsyncMock(return_value=template)

        result = await service.preview(
            uuid.uuid4(),
            uuid.uuid4(),
            TemplatePreviewRequest(sub={"nombre": "Ana"}),
            make_user_session(),
        )

        assert result.variables_used == ["nombre", "saldo"]
        assert result.html == "Hola Ana, saldo {saldo}"
        assert result.subject == "Recordatorio Ana"


class TestSend:
    def _make_email_template(self, **overrides):
        defaults = dict(
            id=uuid.uuid4(),
            channel=ChannelName.EMAIL,
            status=TemplateStatus.ACTIVE,
            body="Hola {nombre}",
            subject="Asunto original",
        )
        defaults.update(overrides)
        template = MagicMock(**defaults)
        return template

    async def test_recipient_other_than_own_email_raises_422(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        template_repo.get_by_id_and_portfolio = AsyncMock(
            return_value=self._make_email_template()
        )

        with patch(
            "messaging.templates.services.template_service._DISPATCHER"
        ) as mock_dispatcher:
            mock_dispatcher.send = AsyncMock(return_value=(True, None, None))
            with pytest.raises(HTTPException) as exc_info:
                await service.send(
                    uuid.uuid4(),
                    uuid.uuid4(),
                    TemplateSendRequest(to="victima@otro.com", sub={}),
                    make_user_session(email="a@b.com"),
                )
        assert exc_info.value.status_code == 422
        mock_dispatcher.send.assert_not_called()

    async def test_non_email_channel_raises_422(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        template = self._make_email_template(channel=ChannelName.SMS)
        template_repo.get_by_id_and_portfolio = AsyncMock(return_value=template)

        with pytest.raises(HTTPException) as exc_info:
            await service.send(
                uuid.uuid4(),
                uuid.uuid4(),
                TemplateSendRequest(to="a@b.com", sub={}),
                make_user_session(email="a@b.com"),
            )
        assert exc_info.value.status_code == 422

    async def test_inactive_template_raises_422(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        template = self._make_email_template(status=TemplateStatus.DRAFT)
        template_repo.get_by_id_and_portfolio = AsyncMock(return_value=template)

        with pytest.raises(HTTPException) as exc_info:
            await service.send(
                uuid.uuid4(),
                uuid.uuid4(),
                TemplateSendRequest(to="a@b.com", sub={}),
                make_user_session(email="a@b.com"),
            )
        assert exc_info.value.status_code == 422

    async def test_sends_through_the_gateway_using_the_template_channel(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio = make_portfolio(country="MX")
        portfolio_repo.get_by_id = AsyncMock(return_value=portfolio)
        template = self._make_email_template()
        template_repo.get_by_id_and_portfolio = AsyncMock(return_value=template)

        with patch(
            "messaging.templates.services.template_service._DISPATCHER"
        ) as mock_dispatcher:
            mock_dispatcher.send = AsyncMock(
                return_value=(True, {"a@b.com": "id-1"}, "sending-1")
            )
            result = await service.send(
                uuid.uuid4(),
                uuid.uuid4(),
                TemplateSendRequest(to="a@b.com", subject=None, sub={"nombre": "Ana"}),
                make_user_session(email="a@b.com"),
            )

        mock_dispatcher.send.assert_awaited_once()
        call = mock_dispatcher.send.await_args
        assert (
            call.args[0] == ChannelName.EMAIL
        )  # canal de la plantilla, no hardcodeado
        assert call.args[1] == ["a@b.com"]
        assert (
            call.args[2] == "Hola {nombre}"
        )  # sin resolver -- lo hace el proveedor con `sub`
        assert call.kwargs["subject"] == "Asunto original"
        assert call.kwargs["sub"] == [{"nombre": "Ana"}]
        assert call.kwargs["credential_service"] is service._credential_service
        assert call.kwargs["country"] == "MX"
        assert result.message

    async def test_custom_subject_overrides_template_subject(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        template = self._make_email_template()
        template_repo.get_by_id_and_portfolio = AsyncMock(return_value=template)

        with patch(
            "messaging.templates.services.template_service._DISPATCHER"
        ) as mock_dispatcher:
            mock_dispatcher.send = AsyncMock(return_value=(True, None, None))
            await service.send(
                uuid.uuid4(),
                uuid.uuid4(),
                TemplateSendRequest(to="a@b.com", subject="Asunto custom", sub={}),
                make_user_session(email="a@b.com"),
            )

        assert mock_dispatcher.send.await_args.kwargs["subject"] == "Asunto custom"

    async def test_gateway_failure_raises_502(self):
        service, template_repo, portfolio_repo = build_service()
        portfolio_repo.get_by_id = AsyncMock(return_value=make_portfolio())
        template = self._make_email_template()
        template_repo.get_by_id_and_portfolio = AsyncMock(return_value=template)

        with patch(
            "messaging.templates.services.template_service._DISPATCHER"
        ) as mock_dispatcher:
            mock_dispatcher.send = AsyncMock(return_value=(False, None, None))
            with pytest.raises(HTTPException) as exc_info:
                await service.send(
                    uuid.uuid4(),
                    uuid.uuid4(),
                    TemplateSendRequest(to="a@b.com", sub={}),
                    make_user_session(email="a@b.com"),
                )
        assert exc_info.value.status_code == 502
