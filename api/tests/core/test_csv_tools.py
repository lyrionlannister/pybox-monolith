"""Neutralización de fórmulas en CSV exportados."""

import polars as pl

from core.tools.csv_tools import neutralize_formulas


def test_text_cells_starting_like_formulas_are_prefixed():
    df = pl.DataFrame(
        {
            "nombre": ['=HYPERLINK("http://x")', "+1", "-2", "@SUM(A1)", "Ana"],
            "monto": [1, 2, -3, 4, 5],
        }
    )
    out = neutralize_formulas(df)
    assert out["nombre"].to_list() == [
        '\'=HYPERLINK("http://x")',
        "'+1",
        "'-2",
        "'@SUM(A1)",
        "Ana",
    ]
    assert out["monto"].to_list() == [1, 2, -3, 4, 5]


def test_nulls_and_frames_without_text_are_untouched():
    df = pl.DataFrame({"nombre": [None, "x"], "n": [1, 2]})
    assert neutralize_formulas(df)["nombre"].to_list() == [None, "x"]
    numeric = pl.DataFrame({"n": [1, 2]})
    assert neutralize_formulas(numeric).equals(numeric)
