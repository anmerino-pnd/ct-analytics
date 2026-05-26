"""
Orquestador de ingesta incremental.

Flujo:
    1. Lee watermark de orders_historicos.parquet.
    2. Extrae de Mongo lo que falta.
    3. Procesa con build_both_dfs + enrich_items.
    4. Append a los parquets históricos.

Uso:
    from pulse.etl.ingest import run_ingest
    
    resultado = run_ingest()
    print(resultado)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from pulse.config.paths import PROCESSED
from pulse.etl.incremental import (
    contar_pendientes,
    extract_incremental,
    leer_watermark,
)
from pulse.etl.load import save_parquet
from pulse.etl.transform import build_both_dfs, enrich_items

log = logging.getLogger(__name__)

ORDERS_HIST = PROCESSED / "orders_historicos.parquet"
ITEMS_HIST = PROCESSED / "items_historicos.parquet"


@dataclass
class IngestResult:
    """Resumen de una corrida de ingesta."""
    watermark_anterior: Optional[datetime]
    watermark_nuevo: Optional[datetime]
    n_orders_nuevos: int
    n_items_nuevos: int
    n_orders_total: int
    n_items_total: int
    skipped: bool

    def __str__(self) -> str:
        if self.skipped:
            return f"⏭️  Sin pedidos nuevos (watermark: {self.watermark_anterior})"
        return (
            f"✅ Ingesta OK\n"
            f"   Watermark: {self.watermark_anterior} → {self.watermark_nuevo}\n"
            f"   Nuevos:    {self.n_orders_nuevos:,} pedidos, {self.n_items_nuevos:,} items\n"
            f"   Total:     {self.n_orders_total:,} pedidos, {self.n_items_total:,} items"
        )


def run_ingest(fecha_fin: Optional[datetime] = None) -> IngestResult:
    """
    Ejecuta una corrida de ingesta incremental.

    Args:
        fecha_fin: tope superior de fechas a extraer. None = ahora.
            Útil para pruebas (ej. "qué pasaría si corriera el 2026-03-15").

    Returns:
        IngestResult con métricas de la corrida.
    """
    watermark = leer_watermark(ORDERS_HIST)
    if watermark is None:
        log.warning(
            "No existe %s. Esta es una primera corrida — extrayendo TODO el histórico. "
            "Si no es lo que quieres, aborta.",
            ORDERS_HIST,
        )

    n_pendientes = contar_pendientes(watermark, fecha_fin)
    log.info("Watermark actual: %s", watermark)
    log.info("Pedidos pendientes de cargar: %s", f"{n_pendientes:,}")

    if n_pendientes == 0:
        n_orders_total = _contar_filas(ORDERS_HIST)
        n_items_total = _contar_filas(ITEMS_HIST)
        return IngestResult(
            watermark_anterior=watermark,
            watermark_nuevo=watermark,
            n_orders_nuevos=0,
            n_items_nuevos=0,
            n_orders_total=n_orders_total,
            n_items_total=n_items_total,
            skipped=True,
        )

    cursor = extract_incremental(watermark=watermark, fecha_fin=fecha_fin)
    df_orders_nuevos, df_items_nuevos = build_both_dfs(cursor)
    df_items_nuevos = enrich_items(df_items_nuevos)

    log.info(
        "Extraídos: %s pedidos, %s items",
        f"{len(df_orders_nuevos):,}",
        f"{len(df_items_nuevos):,}",
    )

    # Orders: un order_id = una fila → dedup por order_id
    df_orders_total = _append_parquet(
        path=ORDERS_HIST,
        df_nuevo=df_orders_nuevos,
        nombre_save="orders_historicos",
        dedup_keys=["order_id"],
    )

    # Items: N items por order → dedup por (order_id, clave)
    df_items_total = _append_parquet(
        path=ITEMS_HIST,
        df_nuevo=df_items_nuevos,
        nombre_save="items_historicos",
        dedup_keys=["order_id", "clave"],
    )

    nuevo_watermark = df_orders_total["fecha"].max().to_pydatetime()

    return IngestResult(
        watermark_anterior=watermark,
        watermark_nuevo=nuevo_watermark,
        n_orders_nuevos=len(df_orders_nuevos),
        n_items_nuevos=len(df_items_nuevos),
        n_orders_total=len(df_orders_total),
        n_items_total=len(df_items_total),
        skipped=False,
    )


def _append_parquet(
    path,
    df_nuevo: pd.DataFrame,
    nombre_save: str,
    dedup_keys: list[str],
) -> pd.DataFrame:
    """
    Append-only: si el archivo existe, lo lee, concatena con `df_nuevo`,
    deduplica por `dedup_keys` y reescribe.

    Args:
        path: archivo parquet de destino.
        df_nuevo: filas nuevas a appendear.
        nombre_save: nombre para save_parquet (sin extensión).
        dedup_keys: columnas que identifican unívocamente una fila.
            Para orders: ["order_id"].
            Para items:  ["order_id", "clave"].
    """
    if path.exists():
        df_existente = pd.read_parquet(path)
        df_combinado = pd.concat([df_existente, df_nuevo], ignore_index=True)
    else:
        df_combinado = df_nuevo

    faltantes = [k for k in dedup_keys if k not in df_combinado.columns]
    if faltantes:
        raise ValueError(
            f"Las claves de deduplicación {faltantes} no existen en el DataFrame "
            f"de {nombre_save}. Columnas disponibles: {df_combinado.columns.tolist()}"
        )

    antes = len(df_combinado)
    df_combinado = df_combinado.drop_duplicates(subset=dedup_keys, keep="last")
    duplicados = antes - len(df_combinado)

    if duplicados > 0:
        pct_dup = duplicados / antes * 100
        if pct_dup > 20:
            log.error(
                "⚠️  Deduplicados %s registros (%.1f%%) en %s usando %s. "
                "Esto es mucho — revisa que las claves de dedup sean las correctas.",
                f"{duplicados:,}",
                pct_dup,
                nombre_save,
                dedup_keys,
            )
        else:
            log.info(
                "Deduplicados %s registros (%.1f%%) en %s",
                f"{duplicados:,}",
                pct_dup,
                nombre_save,
            )

    save_parquet(df_combinado, nombre_save)
    return df_combinado


def _contar_filas(path) -> int:
    """Cuenta filas de un parquet sin cargarlo entero."""
    if not path.exists():
        return 0
    import pyarrow.parquet as pq
    return pq.ParquetFile(path).metadata.num_rows