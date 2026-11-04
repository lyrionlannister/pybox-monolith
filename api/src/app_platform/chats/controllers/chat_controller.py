"""Endpoints de chats: REST para historial/mensajes y WebSocket en tiempo real."""

import asyncio
import json
import uuid

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from app_platform.chats.dependencies import ChatServiceDep
from app_platform.chats.websocket.connection_manager import ws_manager
from core.config.api_router import APIRouter
from core.config.logger import logger
from core.security.dependencies import WsSessionGuard, get_ws_session

router = APIRouter(prefix="/chats", tags=["Chats"])

_IDLE_TIMEOUT_SECONDS = 1800


@router.websocket("/ws")
async def chat_ws(ws: WebSocket, service: ChatServiceDep):
    try:
        session = await get_ws_session(ws)
    except HTTPException:
        await ws.close(code=1008)
        return

    await ws_manager.connect(session.user_id, ws)
    guard = WsSessionGuard(session)
    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    ws.receive_text(), timeout=_IDLE_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                logger.info("[chat_ws] idle timeout | user_id=%s", session.user_id)
                try:
                    await ws.close(code=1001)
                except Exception:
                    pass
                break

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

                if event == "list_chats":
                    chats = await service.get_user_chats(session.user_id)
                    await reply(
                        "chats",
                        [json.loads(c.model_dump_json(by_alias=True)) for c in chats],
                    )

                elif event == "create_direct_chat":
                    peer_id_raw = data.get("peerId")
                    if peer_id_raw:
                        peer_id = uuid.UUID(str(peer_id_raw))
                        chat = await service.find_or_create_direct_chat(
                            session.user_id, peer_id
                        )
                        await reply(
                            "chat", json.loads(chat.model_dump_json(by_alias=True))
                        )

                elif event == "list_messages":
                    chat_id_raw = data.get("chatId")
                    if chat_id_raw:
                        chat_id = uuid.UUID(str(chat_id_raw))
                        before = data.get("before")
                        limit = data.get("limit", 50)
                        page = await service.list_messages(
                            chat_id, session.user_id, before, limit
                        )
                        await reply(
                            "messages", json.loads(page.model_dump_json(by_alias=True))
                        )

                elif event == "send_message":
                    chat_id_raw = data.get("chatId")
                    body = data.get("body", "")
                    if chat_id_raw:
                        chat_id = uuid.UUID(str(chat_id_raw))
                        msg_schema, recipient_ids = await service.send_message(
                            chat_id, session.user_id, body
                        )
                        msg_data = json.loads(msg_schema.model_dump_json(by_alias=True))
                        for uid in recipient_ids:
                            await ws_manager.send_to_user(uid, "message", msg_data)
                        await reply("message", msg_data)

                elif event == "read":
                    chat_id_raw = data.get("chatId")
                    message_ids_raw = data.get("messageIds", [])
                    if chat_id_raw and message_ids_raw:
                        chat_id = uuid.UUID(str(chat_id_raw))
                        message_ids = [uuid.UUID(str(mid)) for mid in message_ids_raw]
                        other_ids = await service.mark_read(
                            chat_id, session.user_id, message_ids
                        )
                        read_data = {
                            "chatId": str(chat_id),
                            "messageIds": [str(mid) for mid in message_ids],
                            "readerId": str(session.user_id),
                        }
                        for uid in other_ids:
                            await ws_manager.send_to_user(uid, "read", read_data)

                elif event == "create_group_chat":
                    title = data.get("title", "")
                    member_ids_raw = data.get("memberIds", [])
                    member_ids = [uuid.UUID(str(mid)) for mid in member_ids_raw]
                    chat = await service.create_group_chat(session, title, member_ids)
                    await reply("chat", json.loads(chat.model_dump_json(by_alias=True)))

                elif event == "list_group_members":
                    chat_id_raw = data.get("chatId")
                    if chat_id_raw:
                        chat_id = uuid.UUID(str(chat_id_raw))
                        members = await service.list_members(chat_id, session.user_id)
                        await reply(
                            "group_members",
                            {
                                "chatId": str(chat_id),
                                "members": [
                                    json.loads(m.model_dump_json(by_alias=True))
                                    for m in members
                                ],
                            },
                        )

                elif event == "add_group_member":
                    chat_id_raw = data.get("chatId")
                    candidate_id_raw = data.get("userId")
                    if chat_id_raw and candidate_id_raw:
                        chat_id = uuid.UUID(str(chat_id_raw))
                        candidate_id = uuid.UUID(str(candidate_id_raw))
                        chat, other_ids = await service.add_member(
                            session, chat_id, candidate_id
                        )
                        chat_data = json.loads(chat.model_dump_json(by_alias=True))
                        await reply("chat", chat_data)
                        candidate_summary = await service.get_chat_summary_for(
                            chat_id, candidate_id
                        )
                        await ws_manager.send_to_user(
                            candidate_id,
                            "chat",
                            json.loads(
                                candidate_summary.model_dump_json(by_alias=True)
                            ),
                        )
                        update_data = {
                            "chatId": str(chat_id),
                            "memberCount": chat_data["memberCount"],
                        }
                        for uid in other_ids:
                            if uid != session.user_id:
                                await ws_manager.send_to_user(
                                    uid, "group_updated", update_data
                                )

                elif event == "remove_group_member":
                    chat_id_raw = data.get("chatId")
                    target_id_raw = data.get("userId")
                    if chat_id_raw and target_id_raw:
                        chat_id = uuid.UUID(str(chat_id_raw))
                        target_id = uuid.UUID(str(target_id_raw))
                        recipient_ids = await service.remove_member(
                            session, chat_id, target_id
                        )
                        await reply(
                            "member_removed",
                            {"chatId": str(chat_id), "userId": str(target_id)},
                        )
                        await ws_manager.send_to_user(
                            target_id,
                            "member_removed",
                            {"chatId": str(chat_id), "userId": str(target_id)},
                        )
                        update_data = {
                            "chatId": str(chat_id),
                            "memberCount": len(recipient_ids),
                        }
                        for uid in recipient_ids:
                            if uid != session.user_id:
                                await ws_manager.send_to_user(
                                    uid, "group_updated", update_data
                                )

                elif event == "read_all":
                    chat_id_raw = data.get("chatId")
                    if chat_id_raw:
                        chat_id = uuid.UUID(str(chat_id_raw))
                        other_ids, msg_ids = await service.mark_all_read(
                            chat_id, session.user_id
                        )
                        if msg_ids:
                            read_data = {
                                "chatId": str(chat_id),
                                "messageIds": [str(mid) for mid in msg_ids],
                                "readerId": str(session.user_id),
                            }
                            for uid in other_ids:
                                await ws_manager.send_to_user(uid, "read", read_data)

            except HTTPException as e:
                await ws.send_json({"event": "error", "data": {"detail": e.detail}})

    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(session.user_id, ws)
