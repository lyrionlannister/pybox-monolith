"""Endpoints de chats de WhatsApp: REST para historial y WebSocket en tiempo real."""

import json
import uuid
from typing import Annotated

from fastapi import HTTPException, Query, WebSocket, WebSocketDisconnect

from core.config.api_router import APIRouter
from core.security.dependencies import (
    CurrentSession,
    WsSessionGuard,
    get_ws_session,
)
from messaging.whatsapp.dependencies import WhatsAppChatServiceDep
from messaging.whatsapp.schemas.whatsapp_chat_schemas import (
    WhatsAppChatAssignRequest,
    WhatsAppChatDetailsResponse,
    WhatsAppChatListResponse,
    WhatsAppChatResponse,
    WhatsAppMessageResponse,
)
from messaging.whatsapp.websocket.connection_manager import whatsapp_ws_manager

router = APIRouter(prefix="/whatsapp/chats", tags=["Chats de WhatsApp"])


@router.get(
    "/",
    response_model=WhatsAppChatListResponse,
    summary="Listar hilos de WhatsApp (filtrado por asignación)",
)
async def list_whatsapp_chats(
    session: CurrentSession,
    service: WhatsAppChatServiceDep,
    organization_id: Annotated[uuid.UUID | None, Query(alias="organizationId")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> WhatsAppChatListResponse:
    items, total = await service.list_chats(page, page_size, session, organization_id)
    return WhatsAppChatListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.get(
    "/{chat_id}/messages",
    response_model=list[WhatsAppMessageResponse],
    summary="Listar mensajes de un hilo de WhatsApp",
)
async def list_whatsapp_chat_messages(
    chat_id: uuid.UUID,
    session: CurrentSession,
    service: WhatsAppChatServiceDep,
    organization_id: Annotated[uuid.UUID, Query(alias="organizationId")],
) -> list[WhatsAppMessageResponse]:
    messages = await service.list_messages(chat_id, organization_id, session)
    return [WhatsAppMessageResponse.model_validate(message) for message in messages]


@router.patch(
    "/{chat_id}/assign",
    response_model=WhatsAppChatResponse,
    summary="Reasignar un hilo (solo admin)",
)
async def assign_whatsapp_chat(
    chat_id: uuid.UUID,
    body: WhatsAppChatAssignRequest,
    session: CurrentSession,
    service: WhatsAppChatServiceDep,
    organization_id: Annotated[uuid.UUID, Query(alias="organizationId")],
) -> WhatsAppChatResponse:
    chat = await service.assign(
        chat_id, organization_id, body.assigned_user_id, session
    )
    return WhatsAppChatResponse.model_validate(chat)


@router.get(
    "/{chat_id}/details",
    response_model=WhatsAppChatDetailsResponse,
    summary="Detalles del hilo: deudor, portafolio, campaña y créditos asociados",
)
async def get_whatsapp_chat_details(
    chat_id: uuid.UUID,
    session: CurrentSession,
    service: WhatsAppChatServiceDep,
    organization_id: Annotated[uuid.UUID, Query(alias="organizationId")],
) -> WhatsAppChatDetailsResponse:
    return await service.get_chat_details(chat_id, organization_id, session)


@router.websocket("/ws")
async def whatsapp_chat_ws(ws: WebSocket, service: WhatsAppChatServiceDep):
    try:
        session = await get_ws_session(ws)
    except HTTPException:
        await ws.close(code=1008)
        return

    await whatsapp_ws_manager.connect(session.user_id, ws)
    guard = WsSessionGuard(session)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                session = await guard.current()
            except HTTPException:
                await ws.close(code=1008)
                break

            try:
                msg = json.loads(raw)
                event = msg.get("event")
                data = msg.get("data", {})
            except json.JSONDecodeError, AttributeError:
                continue

            try:
                req_id = data.get("requestId") if isinstance(data, dict) else None

                async def reply(out_event: str, out_data) -> None:
                    payload = {"event": out_event, "data": out_data}
                    if req_id:
                        payload["requestId"] = req_id
                    await ws.send_json(payload)

                organization_id_raw = (
                    data.get("organizationId") if isinstance(data, dict) else None
                )
                organization_id = (
                    uuid.UUID(str(organization_id_raw)) if organization_id_raw else None
                )

                if event == "list_chats":
                    # Sin organizationId el listado abarca todas las organizaciones
                    # accesibles; el resto de eventos sí exigen una organización porque
                    # operan sobre un hilo concreto.
                    page = int(data.get("page", 1))
                    page_size = int(data.get("pageSize", 20))
                    items, total = await service.list_chats(
                        page, page_size, session, organization_id
                    )
                    chats_data = [
                        json.loads(c.model_dump_json(by_alias=True)) for c in items
                    ]
                    await reply(
                        "chats",
                        {
                            "items": chats_data,
                            "total": total,
                            "page": page,
                            "pageSize": page_size,
                        },
                    )

                elif organization_id is None:
                    continue

                elif event == "list_messages":
                    chat_id_raw = data.get("chatId")
                    if chat_id_raw:
                        chat_id = uuid.UUID(str(chat_id_raw))
                        messages = await service.list_messages(
                            chat_id, organization_id, session
                        )
                        messages_data = [
                            json.loads(
                                WhatsAppMessageResponse.model_validate(
                                    m
                                ).model_dump_json(by_alias=True)
                            )
                            for m in messages
                        ]
                        await reply("messages", messages_data)

                elif event == "send_message":
                    chat_id_raw = data.get("chatId")
                    body = data.get("body", "")
                    if chat_id_raw and body:
                        chat_id = uuid.UUID(str(chat_id_raw))
                        message = await service.send_message(
                            chat_id, organization_id, body, session
                        )
                        msg_data = json.loads(
                            WhatsAppMessageResponse.model_validate(
                                message
                            ).model_dump_json(by_alias=True)
                        )
                        await reply("message", msg_data)

            except HTTPException as e:
                error_payload = {"event": "error", "data": {"detail": e.detail}}
                if req_id:
                    error_payload["requestId"] = req_id
                await ws.send_json(error_payload)

    except WebSocketDisconnect:
        whatsapp_ws_manager.disconnect(session.user_id, ws)
