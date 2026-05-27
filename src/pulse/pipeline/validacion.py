"""
Validaciones de calidad del pipeline.

Cada función recibe el DataFrame producido por un paso y verifica que
cumple invariantes esperadas. Si una validación falla, lanza
`QualityCheckFailed` con un mensaje claro de qué falló y por qué.

La política es estricta: cualquier validación que falle aborta el pipeline.
Esto es a propósito — preferimos que el cron falle ruidoso a que el
dashboard sirva datos corruptos silenciosamente.

API pública:
    validar_ingest(df_orders_nuevo, df_orders_anterior)
    validar_clientes_segmentados(df_clientes)
    validar_distribucion_segmentos(df_clientes, max_pct=0.5)
    validar_temporalidad_mensual(df_mensual)
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


class QualityCheckFailed(Exception):
    """Excepción lanzada cuando una validación de calidad falla."""
    pass


# ----------------------------------------------------------------
# Validaciones individuales
# ----------------------------------------------------------------
def validar_ingest(
    n_orders_post: int,
    n_orders_pre: Optional[int],
    max_caida_pct: float = 5.0,
) -> None:
    """
    Verifica que el ingest no haya destruido datos.

    Args:
        n_orders_post: Número de pedidos después del ingest.
        n_orders_pre: Número de pedidos antes (None si es la primera corrida).
        max_caida_pct: % máximo de caída permitido (default 5%).

    Raises:
        QualityCheckFailed: si los pedidos cayeron más del umbral.
    """
    if n_orders_pre is None or n_orders_pre == 0:
        log.info("Primera corrida (sin estado previo). Saltando validación de ingest.")
        return

    caida_pct = (n_orders_pre - n_orders_post) / n_orders_pre * 100

    if caida_pct > max_caida_pct:
        raise QualityCheckFailed(
            f"El ingest destruyó datos: "
            f"{n_orders_pre:,} → {n_orders_post:,} pedidos "
            f"(caída {caida_pct:.1f}%, máximo permitido {max_caida_pct}%). "
            f"Revisa la lógica de dedup en pulse.etl.ingest."
        )

    log.info(
        "✅ Ingest OK: %s → %s pedidos (cambio %+.1f%%)",
        f"{n_orders_pre:,}",
        f"{n_orders_post:,}",
        -caida_pct,
    )


def validar_clientes_segmentados(df_clientes: pd.DataFrame) -> None:
    """
    Verifica que todos los clientes recibieron segmento y no hay nulos en features.
    """
    if df_clientes.empty:
        raise QualityCheckFailed(
            "df_clientes está vacío tras segmentación. "
            "Esto sugiere que la ventana temporal no incluye pedidos."
        )

    # 1. Sin nulos en segmento
    n_sin_segmento = df_clientes["segmento_cluster"].isna().sum()
    if n_sin_segmento > 0:
        raise QualityCheckFailed(
            f"{n_sin_segmento:,} clientes quedaron sin segmento asignado. "
            f"Esto NO debería pasar — revisa SegmentadorClientes.predict()."
        )

    # 2. Sin nulos en features
    features = ["recency", "frequency", "monetary", "dias_entre_compras"]
    nulos = df_clientes[features].isna().sum()
    cols_con_nulos = nulos[nulos > 0].to_dict()
    if cols_con_nulos:
        raise QualityCheckFailed(
            f"Hay nulos en features RFM: {cols_con_nulos}. "
            f"La imputación de single-buyers debió cubrirlos. "
            f"Revisa pulse.analytics.rfm._imputar_single_buyers."
        )

    # 3. Cluster IDs en rango válido
    cluster_max = df_clientes["cluster_id"].max()
    cluster_min = df_clientes["cluster_id"].min()
    if cluster_min < 0 or cluster_max > 4:
        raise QualityCheckFailed(
            f"cluster_id fuera de rango [0, 4]: "
            f"min={cluster_min}, max={cluster_max}."
        )

    log.info("✅ Segmentación OK: %s clientes, sin nulos", f"{len(df_clientes):,}")


def validar_distribucion_segmentos(
    df_clientes: pd.DataFrame,
    max_pct_un_segmento: float = 50.0,
) -> None:
    """
    Verifica que ningún segmento absorba más del X% de los clientes.

    Esto es un canario contra el bug del log-transform que viste antes
    (donde MVPs absorbía 92% de los clientes por un pipeline mal armado).
    """
    distribucion = df_clientes["segmento_cluster"].value_counts(normalize=True) * 100
    max_pct = distribucion.max()
    segmento_dominante = distribucion.idxmax()

    if max_pct > max_pct_un_segmento:
        raise QualityCheckFailed(
            f"El segmento '{segmento_dominante}' absorbe {max_pct:.1f}% "
            f"de los clientes (máximo permitido {max_pct_un_segmento}%). "
            f"Esto sugiere un problema en el pipeline de scoring "
            f"(escalas distintas entre fit y predict, datos sin imputar, etc)."
        )

    log.info(
        "✅ Distribución de segmentos OK (máximo: %s con %.1f%%)",
        segmento_dominante,
        max_pct,
    )


def validar_temporalidad_mensual(
    df_mensual: pd.DataFrame,
    df_clientes: pd.DataFrame,
    tolerancia_pct: float = 2.0,
) -> None:
    """
    Cross-check: la suma de pedidos en el agregado mensual debe coincidir
    (dentro de tolerancia) con la suma de frequency de los clientes
    en la misma ventana.

    Si difieren mucho, hay un filtro inconsistente entre el cálculo de RFM
    y el de temporalidad (ventana distinta, segmentos no cruzados, etc).
    """
    if df_mensual.empty:
        log.warning("df_mensual vacío. Saltando cross-check con frequency.")
        return

    pedidos_temporal = df_mensual["pedidos"].sum()
    pedidos_rfm = df_clientes["frequency"].sum()

    if pedidos_rfm == 0:
        raise QualityCheckFailed(
            "La suma de frequency es 0. Esto NO debería pasar."
        )

    diff_pct = abs(pedidos_temporal - pedidos_rfm) / pedidos_rfm * 100

    if diff_pct > tolerancia_pct:
        raise QualityCheckFailed(
            f"Inconsistencia entre temporalidad y RFM: "
            f"temporal={pedidos_temporal:,} vs RFM={pedidos_rfm:,} "
            f"(diferencia {diff_pct:.1f}%, tolerancia {tolerancia_pct}%). "
            f"Probablemente las ventanas temporales no coinciden."
        )

    log.info(
        "✅ Cross-check temporalidad-RFM OK (diferencia %.2f%%)",
        diff_pct,
    )