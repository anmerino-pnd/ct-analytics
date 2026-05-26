"""
Extracción incremental desde MongoDB.

Lógica:
1. Lee el watermark = max(fecha) del parquet histórico.
2. Consulta a MongoDB solo los documentos con fecha > watermark.
3. Retorna un cursor (generator-based) que se procesa con build_both_dfs.

Si no existe el parquet histórico (primera corrida o sistema nuevo),
retorna None — el caller decide qué hacer (full backfill o error).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from pulse.config.paths import PROCESSED
from pulse.etl.extraction import (
    ESTATUS_CANCELADO,
    _build_status_filter,
    get_collection,
)


def leer_watermark(parquet_path: Path) -> Optional[datetime]:
    """
    Devuelve el max(fecha) del parquet histórico, o None si el archivo no existe.
    
    Lee únicamente la columna 'fecha' para no cargar todo el dataset a memoria.
    """
    if not parquet_path.exists():
        return None

    # pyarrow lee solo la columna que pedimos; eficiente incluso con parquets grandes
    df_fechas = pd.read_parquet(parquet_path, columns=["fecha"])
    if df_fechas.empty:
        return None

    return df_fechas["fecha"].max().to_pydatetime()


def extract_incremental(
    watermark: Optional[datetime] = None,
    fecha_fin: Optional[datetime] = None,
    batch_size: int = 5000,
) -> Iterable[dict]:
    """
    Yields documentos de Mongo con fecha > watermark.

    Args:
        watermark: fecha mínima exclusiva. Si es None, extrae TODO el histórico
            disponible (úsalo solo para backfill inicial).
        fecha_fin: fecha máxima inclusiva. Si es None, usa "ahora" (UTC).
        batch_size: tamaño de batch para el cursor de Mongo.
    """
    collection = get_collection()

    if fecha_fin is None:
        fecha_fin = datetime.now(tz=timezone.utc)

    fecha_filter = {"$lte": fecha_fin}
    if watermark is not None:
        # Strictly greater than → no duplicamos el último pedido del parquet
        fecha_filter["$gt"] = watermark

    query = {
        **_build_status_filter(ESTATUS_CANCELADO),
        "pedido.tipo": "CTonline",
        "pedido.fecha": fecha_filter,
        "estatus.Facturado": {"$exists": True},
    }

    projection = {
        "_id": 1,
        "pedido.fecha": 1,
        "pedido.encabezado.cliente": 1,
        "pedido.encabezado.nombre": 1,
        "pedido.encabezado.pago": 1,
        "pedido.encabezado.tipodecambio": 1,
        "pedido.encabezado.iva": 1,
        "pedido.encabezado.plazo": 1,
        "pedido.encabezado.tipoPago": 1,
        "pedido.detalle.producto": 1,
    }

    cursor = collection.find(query, projection).batch_size(batch_size)
    yield from cursor


def contar_pendientes(
    watermark: Optional[datetime],
    fecha_fin: Optional[datetime] = None,
) -> int:
    """
    Cuenta cuántos documentos hay pendientes de cargar.
    Útil para logging antes de procesar.
    """
    collection = get_collection()

    if fecha_fin is None:
        fecha_fin = datetime.now(tz=timezone.utc)

    fecha_filter = {"$lte": fecha_fin}
    if watermark is not None:
        fecha_filter["$gt"] = watermark

    query = {
        **_build_status_filter(ESTATUS_CANCELADO),
        "pedido.tipo": "CTonline",
        "pedido.fecha": fecha_filter,
        "estatus.Facturado": {"$exists": True},
    }

    return collection.count_documents(query)