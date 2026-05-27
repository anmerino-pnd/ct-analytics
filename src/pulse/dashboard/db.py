"""Conexión DuckDB compartida y registro de vistas sobre los parquets.

Una sola conexión por proceso (DuckDB es thread-safe para reads). Cada parquet
en `datos/processed/` se expone como una vista SQL con nombre estable que las
queries de `queries.py` consumen.
"""
from __future__ import annotations

from functools import lru_cache

import duckdb

from pulse.config.paths import PROCESSED

# Paleta de colores y orden canónico de segmentos. Se sirven al frontend
# (embebidos en base.html como JSON global) para que toda figura Plotly
# use la misma codificación.
SEGMENT_COLORS: dict[str, str] = {
    "MVPs":        "#0B3C5D",
    "Alto Valor":  "#328CC1",
    "Ocasionales": "#6CA6C1",
    "En Riesgo":   "#D82822",
    "Hibernando":  "#9AA0A6",
}

SEGMENT_ORDER: list[str] = [
    "MVPs",
    "Alto Valor",
    "Ocasionales",
    "En Riesgo",
    "Hibernando",
]

_VIEWS: dict[str, str] = {
    "segmentos":         "clientes_segmentados.parquet", 
    "orders":            "orders_historicos.parquet",     
    "items":             "items_historicos.parquet",      
    "mba_accionables":   "mba_accionables.parquet",       
    "mba_por_segmento":  "mba_por_segmento.parquet",
    "mba_exclusivas":    "mba_exclusivas.parquet",
    "temp_hora_dia":     "temp_hora_dia.parquet",
    "temp_mes":          "temp_mensual.parquet",         
    "temp_bundles":      "temp_bundles.parquet",
}


@lru_cache(maxsize=1)
def get_connection() -> duckdb.DuckDBPyConnection:
    """Devuelve una conexión DuckDB en memoria con todas las vistas registradas."""
    con = duckdb.connect(":memory:")
    _register_views(con)
    return con


def _register_views(con: duckdb.DuckDBPyConnection) -> None:
    """Registra cada parquet como una vista SQL en la conexión."""
    for name, fname in _VIEWS.items():
        path = (PROCESSED / fname).as_posix()
        con.execute(
            f"CREATE OR REPLACE VIEW {name} AS "
            f"SELECT * FROM read_parquet('{path}')"
        )


def fetch_dicts(
    sql: str,
    params: list | tuple | None = None,
) -> list[dict]:
    """Ejecuta una query parametrizada y devuelve filas como lista de dicts.

    Usar SIEMPRE este helper en `queries.py`. Pasa parámetros como `?` en el SQL
    y como lista en `params`, nunca interpoles valores en el string.
    """
    con = get_connection()
    res = con.execute(sql, params or [])
    columns = [d[0] for d in res.description]
    return [dict(zip(columns, row)) for row in res.fetchall()]
