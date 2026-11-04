"""Parser del CSV/XLSX de envío masivo (documento + destinatario)."""

from __future__ import annotations

import io

import polars as pl
from fastapi import HTTPException, UploadFile, status

from app_platform.documents.utils.upload_limits import read_within_limit

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_ROWS = 10_000
_REQUIRED_COLS = {"tipo_documento", "documento", "destinatario"}
_CSV_MIMES = {"text/csv", "application/csv", "text/plain"}
_XLSX_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}


async def parse_file(file: UploadFile) -> list[dict[str, str]]:
    content = await read_within_limit(file, _MAX_BYTES)

    filename = (file.filename or "").lower()
    mime = (file.content_type or "").lower()

    if filename.endswith(".xlsx") or mime in _XLSX_MIMES:
        df = _read_excel(content)
    else:
        df = _read_csv(content)

    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Columnas obligatorias faltantes: {', '.join(sorted(missing))}",
        )

    if len(df) == 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "El archivo no contiene filas de datos",
        )

    if len(df) > _MAX_ROWS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"El archivo supera el límite de {_MAX_ROWS} filas",
        )

    df = df.with_columns([pl.col(c).cast(pl.Utf8).fill_null("") for c in df.columns])
    return df.to_dicts()


def _read_csv(content: bytes) -> pl.DataFrame:
    try:
        return pl.read_csv(io.BytesIO(content), infer_schema_length=0)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Error al leer CSV: {exc}"
        ) from exc


def _read_excel(content: bytes) -> pl.DataFrame:
    try:
        return pl.read_excel(io.BytesIO(content), infer_schema_length=0)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Error al leer Excel: {exc}"
        ) from exc
