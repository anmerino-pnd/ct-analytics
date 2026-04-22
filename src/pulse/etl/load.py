"""
Módulo de carga/persistencia de datos transformados.
Guarda DataFrames en formato Parquet para análisis posterior.
"""

import pandas as pd
from pulse.config.paths import PROCESSED


def save_parquet(
    df: pd.DataFrame,
    nombre: str,
) -> str:
    """
    Guarda un DataFrame como archivo Parquet.

    Args:
        df: DataFrame a guardar.
        nombre: Nombre del archivo (sin extensión).
        subdir: Subdirectorio dentro de data/.

    Returns:
        Path del archivo guardado.
    """
    
    filepath = PROCESSED / f"{nombre}.parquet"
    df.to_parquet(filepath, index=False)
    print(f"Guardado: {filepath} ({len(df):,} filas)")
    return "success"


def load_parquet(nombre: str, subdir: str = "processed") -> pd.DataFrame:
    """Carga un archivo Parquet previamente guardado."""
    filepath = PROCESSED / f"{nombre}.parquet"
    return pd.read_parquet(filepath)