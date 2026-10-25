"""Nombre de archivo, content-type y clave de objeto para documentos subidos."""

import hashlib
import os
import re
import uuid

from fastapi import HTTPException, status

from app_platform.documents.enums.document_enums import ALLOWED_DOCUMENT_TYPES

_UNSAFE_NAME_CHARS = re.compile(r"[^\w.\- ]")


def resolve_content_type(filename: str | None, declared_type: str | None = None) -> str:
    """Content-type canónico según la extensión, o 415 si no está permitida.

    Lo decide la API a partir de la extensión, no el cliente. Si además el cliente
    declaró un Content-Type, tiene que coincidir: eso es lo que impide subir un
    ejecutable renombrado a .pdf.
    """
    ext = os.path.splitext(filename or "")[1].lower()
    content_type = ALLOWED_DOCUMENT_TYPES.get(ext)
    if content_type is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Solo se permiten archivos PDF, PNG, JPG o WebP",
        )
    if declared_type and declared_type != content_type:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"El contenido del archivo no corresponde a la extensión {ext}",
        )
    return content_type


_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),  # bytes 8-11 son "WEBP", ver verify_magic_bytes
}


def verify_magic_bytes(content: bytes, content_type: str) -> None:
    """Confirma que el contenido real empiece con la firma esperada para
    `content_type`, para que un archivo renombrado (ej. HTML con extensión .pdf) no
    pase solo por tener la extensión correcta. Defensa en profundidad: los tipos
    permitidos ya están acotados a PDF/PNG/JPG/WebP por `resolve_content_type`."""
    signatures = _MAGIC_BYTES.get(content_type, ())
    if not any(content.startswith(sig) for sig in signatures):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "El contenido del archivo no corresponde a su tipo declarado",
        )
    if content_type == "image/webp" and content[8:12] != b"WEBP":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "El contenido del archivo no corresponde a su tipo declarado",
        )


def checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def safe_original_name(name: str | None) -> str:
    """Nombre para mostrar y para el Content-Disposition de la descarga. No se usa para
    construir la clave del objeto, así que no hay riesgo de traversal; se limpia igual
    para que no se cuele en una cabecera."""
    if not name:
        return "documento"
    cleaned = _UNSAFE_NAME_CHARS.sub("_", os.path.basename(name)).strip()
    return cleaned[:255] or "documento"


def generate_uuid7_filename(
    original_name: str | None, default_ext: str = ".pdf"
) -> str:
    """Nombre `<uuid7><ext>` para un archivo recién subido. UUID7 en vez de UUID4: es
    ordenable por tiempo de creación, útil para listar/depurar objetos en el almacén.

    Se usa como `filename`/`original_name` (no solo como clave interna) en los flujos
    donde no tiene sentido guardar el nombre original que trajo el navegador (p. ej.
    documentos de verificación de una entidad, donde el tipo de documento ya lo dice
    todo) — todo archivo subido por esos flujos se nombra y guarda siempre así.
    """
    ext = os.path.splitext(original_name or "")[1].lower() or default_ext
    return f"{uuid.uuid7().hex}{ext}"


def build_object_key(domain: str, owner_id: str, original_name: str) -> str:
    """Clave del objeto: `<dominio>/<dueño>/<uuid7><ext>`.

    `domain` es el prefijo literal que aporta cada dominio dueño del documento
    (`"deudor"`, `"ticket"`, `"portafolio"`, `"notificacion_judicial"`,
    `"entidad_reporte"`, …). Antes venía del enum `DocumentOwnerScope`, que desapareció
    junto con la asociación polimórfica: la organización del almacén la decide ahora el
    dominio que guarda, no un enum global.

    UUID7 (ordenable por tiempo, a diferencia de UUID4) evita colisiones al subir dos
    veces el mismo nombre. No dependemos de que sea impredecible: la clave nunca sale
    de la base de datos.
    """
    ext = os.path.splitext(original_name)[1].lower()
    return f"{domain}/{owner_id}/{uuid.uuid7().hex}{ext}"
