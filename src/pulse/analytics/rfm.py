"""
Cálculo de features RFM (Recency, Frequency, Monetary) + cadencia de compra.

API pública del módulo:
    calcular_rfm_completo(df_orders, fecha_ref=None, ventana_meses=30) -> DataFrame
        Devuelve el DataFrame RFM listo para alimentar el modelo de segmentación:
        recency, frequency, monetary, dias_entre_compras, es_single_buyer
        con la imputación de single-buyers ya aplicada (cadencia → p95).

Las funciones internas (_calcular_features, _imputar_single_buyers) NO deben
usarse fuera de este módulo. El pipeline siempre llama a calcular_rfm_completo
para garantizar que los datos lleguen al modelo sin NaN.

Decisiones de diseño:
- Fecha de referencia: por defecto datetime.now(UTC). Configurable para
  reproducir corridas pasadas o testear escenarios.
- Ventana temporal: 30 meses por defecto (2.5 años). Clientes sin compras
  en ese periodo se excluyen del análisis.
- Cadencia: mediana de días entre compras consecutivas. Robusta a outliers
  (un cliente que se fue de vacaciones 3 meses no luce como "lento").
- Single-buyers: cadencia imputada con percentil 95 de la cadencia observada,
  + flag binario `es_single_buyer` para que el clustering pueda diferenciarlos.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


def calcular_rfm_completo(
    df_orders: pd.DataFrame,
    fecha_ref: Optional[datetime] = None,
    ventana_meses: int = 30,
) -> pd.DataFrame:
    """
    Calcula features RFM completas, listas para alimentar el modelo.

    Args:
        df_orders: DataFrame con columnas [cliente_id, fecha, pago_total].
        fecha_ref: Fecha desde la cual calcular recency. None = ahora (UTC).
        ventana_meses: Cantidad de meses hacia atrás a considerar.

    Returns:
        DataFrame con una fila por cliente y columnas:
        cliente_id, recency, frequency, monetary, dias_entre_compras,
        es_single_buyer.
        Sin valores nulos. Listo para SegmentadorClientes.predict().
    """
    df_rfm = _calcular_features(df_orders, fecha_ref, ventana_meses)
    df_rfm = _imputar_single_buyers(df_rfm)
    return df_rfm


def _calcular_features(
    df_orders: pd.DataFrame,
    fecha_ref: Optional[datetime] = None,
    ventana_meses: int = 30,
) -> pd.DataFrame:
    """
    Calcula recency, frequency, monetary y cadencia desde los pedidos.

    NO aplica imputación — clientes con una sola compra tendrán
    `dias_entre_compras = NaN`. No exponer esta función fuera del módulo.
    """
    _validar_columnas(df_orders, requeridas=["cliente_id", "fecha", "pago_total"])

    if fecha_ref is None:
        fecha_ref = datetime.now(tz=timezone.utc)
    elif fecha_ref.tzinfo is None:
        # Asumir UTC si llega naive — consistente con cómo se guardan las fechas
        fecha_ref = fecha_ref.replace(tzinfo=timezone.utc)

    fecha_corte = fecha_ref - timedelta(days=ventana_meses * 30)

    log.info(
        "RFM: fecha_ref=%s, ventana=%s meses, fecha_corte=%s",
        fecha_ref.isoformat(),
        ventana_meses,
        fecha_corte.isoformat(),
    )

    # Filtrar a la ventana temporal
    df = df_orders.copy()
    df["fecha"] = pd.to_datetime(df["fecha"], utc=True)
    n_antes = len(df)
    df = df[df["fecha"] >= fecha_corte]
    log.info(
        "Pedidos en ventana: %s/%s (%.1f%%)",
        f"{len(df):,}",
        f"{n_antes:,}",
        len(df) / n_antes * 100 if n_antes else 0,
    )

    # Agregaciones R/F/M
    df_sorted = df.sort_values(["cliente_id", "fecha"])
    rfm = df_sorted.groupby("cliente_id").agg(
        ultima_compra=("fecha", "max"),
        frequency=("fecha", "count"),
        monetary=("pago_total", "sum"),
    )

    # Recency: días desde la última compra hasta la fecha de referencia
    rfm["recency"] = (fecha_ref - rfm["ultima_compra"]).dt.days
    rfm = rfm.drop(columns=["ultima_compra"])

    # Cadencia: mediana de días entre compras consecutivas por cliente.
    # Para clientes con 1 sola compra → NaN (se imputa después).
    cadencia = (
        df_sorted.groupby("cliente_id")["fecha"]
        .apply(_mediana_dias_entre_compras)
        .rename("dias_entre_compras")
    )
    rfm = rfm.join(cadencia)

    rfm = rfm.reset_index()

    log.info(
        "Clientes con features calculadas: %s (single-buyers: %s)",
        f"{len(rfm):,}",
        f"{rfm['dias_entre_compras'].isna().sum():,}",
    )

    return rfm


def _mediana_dias_entre_compras(fechas: pd.Series) -> float:
    """Mediana de días entre compras consecutivas. NaN si hay solo una compra."""
    if len(fechas) < 2:
        return float("nan")
    diffs = fechas.sort_values().diff().dt.days.dropna()
    return float(diffs.median())


def _imputar_single_buyers(df_rfm: pd.DataFrame) -> pd.DataFrame:
    """
    Imputa la cadencia para clientes con una sola compra usando el percentil 95
    de los clientes recurrentes. Agrega el flag `es_single_buyer`.

    Mantiene la lógica idéntica al notebook 04 y al notebook 07 (Fase 2).
    NO exponer fuera del módulo.

    Fallback: si no hay clientes recurrentes (todos son single-buyers),
    usa 365 días como cadencia imputada y emite warning. Este escenario
    es raro pero puede ocurrir en datasets muy chicos o ventanas muy cortas.
    """
    df = df_rfm.copy()

    df["es_single_buyer"] = df["dias_entre_compras"].isna().astype(int)

    p95 = df["dias_entre_compras"].quantile(0.95)

    if pd.isna(p95):
        # No hay clientes recurrentes → no podemos calcular p95.
        # Usamos un valor de fallback razonable: 365 días.
        p95 = 365.0
        log.warning(
            "No hay clientes recurrentes en el dataset. "
            "Imputando single-buyers con valor fallback de %.0f días.",
            p95,
        )

    df["dias_entre_compras"] = df["dias_entre_compras"].fillna(p95)

    n_single = int(df["es_single_buyer"].sum())
    log.info(
        "Imputación single-buyers: %s clientes (%.1f%%) → cadencia=%.0f días (p95)",
        f"{n_single:,}",
        n_single / len(df) * 100 if len(df) else 0,
        p95,
    )

    # Sanity check: no debe quedar ningún NaN
    nulos_post = df[["recency", "frequency", "monetary", "dias_entre_compras"]].isna().sum().sum()
    if nulos_post > 0:
        raise ValueError(
            f"Quedan {nulos_post} valores nulos tras imputación. "
            "Revisa los datos de entrada."
        )

    return df


def _validar_columnas(df: pd.DataFrame, requeridas: list[str]) -> None:
    faltantes = [c for c in requeridas if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"Faltan columnas requeridas: {faltantes}. "
            f"Disponibles: {df.columns.tolist()}"
        )