"""
Derivación de la columna `familia` desde `clave`.

La `familia` es la `clave` sin los dígitos finales:
    PAQLOC010 → PAQLOC
    CAMDAH2MP → CAMDAH

Sirve como agrupación de productos a nivel de categoría para
análisis de canasta de mercado (MBA), donde queremos detectar
patrones "el cliente que compra cámaras Dahua también compra
discos duros para grabación", sin que el modelo se pierda en
las variantes específicas de cada modelo.
"""

from __future__ import annotations

import logging
import re

import pandas as pd

log = logging.getLogger(__name__)

# Patrón compilado una sola vez. Quita TODOS los dígitos de la cadena
# (no solo los del final), lo cual es seguro porque los códigos de familia
# nunca contienen números intercalados (PAQ, CAM, ESD, etc.).
_PATRON_DIGITOS = re.compile(r"\d+")


def derivar_familia(clave: str) -> str|None:
    """
    Aplica la regla `clave → familia` a una clave individual.

    Args:
        clave: SKU completo (ej. "PAQLOC010").

    Returns:
        Familia (ej. "PAQLOC"). Si la clave es None/NaN, retorna None.
    """
    if pd.isna(clave):
        return None
    return _PATRON_DIGITOS.sub("", str(clave))


def agregar_familia(df_items: pd.DataFrame) -> pd.DataFrame:
    """
    Devuelve una copia de `df_items` con la columna `familia` derivada de `clave`.

    Si la columna ya existe, se recalcula (consideramos `clave` como fuente
    de verdad — nunca confiamos en una `familia` preexistente).

    Args:
        df_items: DataFrame con al menos la columna `clave`.

    Returns:
        Copia de df_items con la columna `familia` agregada.

    Raises:
        ValueError: si no existe la columna `clave`.
    """
    if "clave" not in df_items.columns:
        raise ValueError(
            f"El DataFrame no tiene la columna 'clave'. "
            f"Columnas disponibles: {df_items.columns.tolist()}"
        )

    df = df_items.copy()
    df["familia"] = df["clave"].apply(derivar_familia)

    # Métricas de cordura para el log
    n_nulas = df["familia"].isna().sum()
    n_familias_unicas = df["familia"].nunique()
    log.info(
        "Familia derivada: %s familias únicas, %s items con familia nula",
        f"{n_familias_unicas:,}",
        f"{n_nulas:,}",
    )

    return df