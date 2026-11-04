"""Endpoints de audios IVR: listar, reproducir, subir y eliminar en Helena."""

from typing import Annotated, Any

from fastapi import File, Form, Header, Response, UploadFile, status

from app_platform.documents.enums.document_enums import MAX_DOCUMENT_SIZE_BYTES
from app_platform.documents.utils.upload_limits import read_within_limit
from core.config.api_router import APIRouter
from core.security.dependencies import CurrentSession
from core.security.policies.security_policies import (
    require_global_admin,
    require_org_or_global,
)
from messaging.ivr.dependencies import HelenaClientDep

router = APIRouter(prefix="/ivr/audios", tags=["IVR - Audios"])


@router.get("/", summary="Listar audios disponibles en Helena")
async def list_audios(
    session: CurrentSession,
    client: HelenaClientDep,
) -> dict[str, Any]:
    require_org_or_global(session)
    return await client.list_sounds()


@router.get("/{audio_name}/stream", summary="Reproducir/streamear un audio de Helena")
async def stream_audio(
    audio_name: str,
    session: CurrentSession,
    client: HelenaClientDep,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    require_org_or_global(session)
    status_code, headers, content = await client.fetch_sound(audio_name, range_header)
    return Response(content=content, status_code=status_code, headers=headers)


@router.post(
    "/upload", status_code=status.HTTP_201_CREATED, summary="Subir audio a Helena"
)
async def upload_audio(
    session: CurrentSession,
    client: HelenaClientDep,
    file: Annotated[UploadFile, File()],
    user_friendly_name: Annotated[str | None, Form(alias="userFriendlyName")] = None,
    slot_number: Annotated[str | None, Form(alias="slotNumber")] = None,
) -> dict[str, Any]:
    require_global_admin(session)
    buffer = await read_within_limit(file, MAX_DOCUMENT_SIZE_BYTES)
    return await client.upload_sound(
        file_buffer=buffer,
        file_name=file.filename or "audio.wav",
        user_friendly_name=user_friendly_name,
        slot_number=slot_number,
    )


@router.delete("/{audio_name}", summary="Eliminar audio de Helena")
async def delete_audio(
    audio_name: str,
    session: CurrentSession,
    client: HelenaClientDep,
) -> dict[str, Any]:
    require_global_admin(session)
    return await client.delete_sound(audio_name)
