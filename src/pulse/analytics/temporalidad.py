"""
Agregados temporales para el dashboard.

Replica la lógica del notebook 06 en funciones puras. Produce 3 parquets:
    - hora_dia: pedidos por (segmento, día_semana, hora) → heatmaps
    - mensual:  pedidos + revenue por (segmento, año_mes) → evolución
    - bundles:  pedidos + revenue por (regla, segmento, año_mes) → mapa de calor

API pública:
    calcular_temporalidad(df_orders, df_segmentos, df_items, df_accionables, ...) -> dict[str, DataFrame]

Decisiones:
- Ventana temporal: 30 meses por defecto (consistente con RFM).
- Bundles temporales: top 20 reglas accionables por segmento (configurable).
- Sin conversión de timezone: la fecha viene como hora local Hermosillo.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def calcular_temporalidad(
    df_orders: pd.DataFrame,
    df_segmentos: pd.DataFrame,
    df_items: pd.DataFrame,
    df_accionables: pd.DataFrame,
    fecha_ref: Optional[datetime] = None,
    ventana_meses: int = 30,
    top_bundles_por_segmento: int = 20,
) -> dict[str, pd.DataFrame]:
    """
    Genera los 3 agregados temporales del dashboard.

    Args:
        df_orders: DataFrame con [order_id, cliente_id, fecha, pago_total].
        df_segmentos: DataFrame con [cliente_id, segmento_cluster].
        df_items: DataFrame con [order_id, familia].
        df_accionables: DataFrame de reglas accionables (output de calcular_mba).
            Debe contener [segmento, antecedents, consequents, lift].
        fecha_ref: Fecha de referencia (tope superior). None = ahora UTC.
        ventana_meses: Meses hacia atrás a considerar.
        top_bundles_por_segmento: Cuántos bundles por segmento se procesan para
            la vista temporal de bundles.

    Returns:
        dict con tres DataFrames:
        - "hora_dia": [segmento_cluster, dia_semana, dia_nombre, hora, pedidos]
        - "mensual":  [segmento_cluster, año_mes, pedidos, revenue]
        - "bundles":  [regla, segmento_regla, año_mes, pedidos, revenue]
    """
    _validar_columnas(df_orders, ["order_id", "cliente_id", "fecha", "pago_total"])
    _validar_columnas(df_segmentos, ["cliente_id", "segmento_cluster"])

    # 1. Filtrar a la ventana y cruzar con segmento
    df = _preparar_orders_con_segmento(
        df_orders, df_segmentos, fecha_ref, ventana_meses
    )

    if df.empty:
        log.warning("No hay pedidos en la ventana temporal. Retornando DataFrames vacíos.")
        return _empty_result()

    # 2. Feature engineering temporal
    df = _agregar_features_temporales(df)

    # 3. Agregado hora × día × segmento
    agg_hora_dia = _agregar_hora_dia(df)
    log.info("Agregado hora_dia: %s filas", f"{len(agg_hora_dia):,}")

    # 4. Agregado mensual por segmento
    agg_mensual = _agregar_mensual(df)
    log.info("Agregado mensual: %s filas", f"{len(agg_mensual):,}")

    # 5. Bundles temporales (solo si hay reglas accionables)
    if df_accionables.empty:
        log.warning("df_accionables está vacío. Saltando agregado de bundles.")
        agg_bundles = pd.DataFrame()
    else:
        _validar_columnas(df_items, ["order_id", "familia"])
        _validar_columnas(df_accionables, ["segmento", "antecedents", "consequents", "lift"])
        agg_bundles = _agregar_bundles_temporal(
            df, df_items, df_accionables, top_bundles_por_segmento
        )
        log.info("Agregado bundles: %s filas", f"{len(agg_bundles):,}")

    return {
        "hora_dia": agg_hora_dia,
        "mensual": agg_mensual,
        "bundles": agg_bundles,
    }


# ----------------------------------------------------------------
# Helpers internos
# ----------------------------------------------------------------
def _preparar_orders_con_segmento(
    df_orders: pd.DataFrame,
    df_segmentos: pd.DataFrame,
    fecha_ref: Optional[datetime],
    ventana_meses: int,
) -> pd.DataFrame:
    """Cruza orders con segmento y filtra a la ventana temporal."""
    if fecha_ref is None:
        fecha_ref = datetime.now(tz=timezone.utc)
    elif fecha_ref.tzinfo is None:
        fecha_ref = fecha_ref.replace(tzinfo=timezone.utc)

    fecha_corte = fecha_ref - timedelta(days=ventana_meses * 30)

    df = df_orders.copy()
    df["fecha"] = pd.to_datetime(df["fecha"], utc=True)

    n_antes = len(df)
    df = df[(df["fecha"] >= fecha_corte) & (df["fecha"] <= fecha_ref)]
    log.info(
        "Pedidos en ventana [%s, %s]: %s/%s",
        fecha_corte.date(),
        fecha_ref.date(),
        f"{len(df):,}",
        f"{n_antes:,}",
    )

    # Cruce con segmento
    df = df.merge(
        df_segmentos[["cliente_id", "segmento_cluster"]],
        on="cliente_id",
        how="inner",
    )
    log.info("Pedidos con segmento asignado: %s", f"{len(df):,}")

    return df


TIMEZONE_LOCAL = "America/Mexico_City"

def _agregar_features_temporales(df: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega año_mes, dia_semana, dia_nombre, hora en hora LOCAL (CDMX).
    
    Los pedidos en orders_historicos.parquet están guardados en UTC
    (es como llegan de MongoDB). Para que el heatmap muestre hábitos
    de compra en términos comprensibles para marketing, convertimos
    a hora local antes de extraer hora/día.
    """
    df = df.copy()
    fecha_local = df["fecha"].dt.tz_convert(TIMEZONE_LOCAL)
    df["año_mes"]    = fecha_local.dt.strftime("%Y-%m")
    df["dia_semana"] = fecha_local.dt.dayofweek
    df["dia_nombre"] = df["dia_semana"].map(dict(enumerate(DIAS_ES)))
    df["hora"]       = fecha_local.dt.hour
    return df


def _agregar_hora_dia(df: pd.DataFrame) -> pd.DataFrame:
    """Pedidos por (segmento, día_semana, hora). Para los heatmaps del dashboard."""
    agg = (
        df.groupby(["segmento_cluster", "dia_semana", "hora"])
        .size()
        .reset_index(name="pedidos")
    )
    agg["dia_nombre"] = agg["dia_semana"].map(dict(enumerate(DIAS_ES)))
    # Reordenar columnas
    return agg[["segmento_cluster", "dia_semana", "dia_nombre", "hora", "pedidos"]]


def _agregar_mensual(df: pd.DataFrame) -> pd.DataFrame:
    """Pedidos + revenue por (segmento, año_mes). Para la línea temporal."""
    agg = (
        df.groupby(["segmento_cluster", "año_mes"])
        .agg(pedidos=("order_id", "count"), revenue=("pago_total", "sum"))
        .reset_index()
    )
    return agg


def _agregar_bundles_temporal(
    df_orders_con_seg: pd.DataFrame,
    df_items: pd.DataFrame,
    df_accionables: pd.DataFrame,
    top_n: int,
) -> pd.DataFrame:
    """
    Para los top N bundles por segmento, distribuye sus pedidos en el tiempo.

    Lógica:
    1. Tomar top_n reglas por segmento (ordenadas por lift).
    2. Para cada regla, identificar pedidos que la materializan (contienen
       TODAS las familias de antecedente + consecuente).
    3. Agregar por (regla, segmento, año_mes).
    """
    # Top N por segmento
    df_top = (
        df_accionables.sort_values(["segmento", "lift"], ascending=[True, False])
        .groupby("segmento")
        .head(top_n)
        .reset_index(drop=True)
    )

    log.info(
        "Procesando temporalidad de %s reglas (top %s por segmento, %s segmentos)",
        len(df_top),
        top_n,
        df_top["segmento"].nunique(),
    )

    # Pre-indexar items por familia para acelerar las búsquedas
    # (cada regla hace varias intersecciones de sets, mejor pagarlo una vez)
    rows = []
    df_orders_idx = df_orders_con_seg.set_index("order_id")

    for _, regla in df_top.iterrows():
        familias = sorted(set(
            regla["antecedents"].split(", ") + regla["consequents"].split(", ")
        ))

        # Pedidos que contienen TODAS las familias
        df_f = df_items[df_items["familia"].isin(familias)]
        fam_por_pedido = df_f.groupby("order_id")["familia"].nunique()
        pedidos_validos = fam_por_pedido[fam_por_pedido == len(familias)].index

        if len(pedidos_validos) == 0:
            continue

        # Filtrar a los pedidos que están en la ventana y con segmento
        pedidos_en_ventana = df_orders_idx.index.intersection(pedidos_validos)
        if len(pedidos_en_ventana) == 0:
            continue

        df_regla = df_orders_idx.loc[pedidos_en_ventana].copy()
        df_regla["regla"] = regla["antecedents"] + " → " + regla["consequents"]
        df_regla["segmento_regla"] = regla["segmento"]

        rows.append(df_regla[["regla", "segmento_regla", "año_mes", "pago_total"]])

    if not rows:
        return pd.DataFrame(
            columns=["regla", "segmento_regla", "año_mes", "pedidos", "revenue"]
        )

    df_concat = pd.concat(rows, ignore_index=True)
    agg = (
        df_concat.groupby(["regla", "segmento_regla", "año_mes"])
        .agg(pedidos=("pago_total", "count"), revenue=("pago_total", "sum"))
        .reset_index()
    )
    return agg


def _validar_columnas(df: pd.DataFrame, requeridas: list[str]) -> None:
    faltantes = [c for c in requeridas if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"Faltan columnas requeridas: {faltantes}. "
            f"Disponibles: {df.columns.tolist()}"
        )


def _empty_result() -> dict[str, pd.DataFrame]:
    return {
        "hora_dia": pd.DataFrame(),
        "mensual": pd.DataFrame(),
        "bundles": pd.DataFrame(),
    }