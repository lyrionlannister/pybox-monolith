"""Neutralización de fórmulas (CSV injection, CWE-1236) en exportaciones tabulares."""

import polars as pl

_FORMULA_START = r"^[=+\-@\t\r]"


def neutralize_formulas(df: pl.DataFrame) -> pl.DataFrame:
    """Antepone `'` a las celdas de texto que empiezan como fórmula (=, +, -, @,
    tab, CR) para que Excel/Sheets no las ejecuten al abrir el CSV. Los datos
    exportados incluyen valores cargados por terceros (nombres, contactos), así que
    no se puede confiar en su contenido. Las columnas numéricas no se tocan."""
    text_columns = [name for name, dtype in df.schema.items() if dtype == pl.String]
    if not text_columns:
        return df
    return df.with_columns(
        [
            pl.when(pl.col(name).str.contains(_FORMULA_START))
            .then(pl.concat_str([pl.lit("'"), pl.col(name)]))
            .otherwise(pl.col(name))
            .alias(name)
            for name in text_columns
        ]
    )
