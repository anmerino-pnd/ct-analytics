"""
Aplicación del modelo de segmentación a los datos RFM.

Este módulo es el pegamento entre:
    - pulse.analytics.rfm           (calcula features)
    - pulse.modeling.segmentador    (modelo K-Means congelado)

Produce el DataFrame final de clientes segmentados que el dashboard consume.

API pública:
    segmentar_clientes(df_orders, model_version="v1", fecha_ref=None) -> DataFrame
        Pipeline completo orders → RFM → segmentación.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from pulse.analytics.rfm import calcular_rfm_completo
from pulse.modeling.segmentador import SegmentadorClientes

log = logging.getLogger(__name__)


def segmentar_clientes(
    df_orders: pd.DataFrame,
    model_version: str = "v1",
    fecha_ref: Optional[datetime] = None,
    ventana_meses: int = 30,
) -> pd.DataFrame:
    """
    Pipeline completo: orders → features RFM → segmento asignado.

    Args:
        df_orders: DataFrame con [cliente_id, fecha, pago_total].
        model_version: Versión del modelo a usar (default "v1").
        fecha_ref: Fecha de referencia para calcular recency. None = ahora UTC.
        ventana_meses: Ventana temporal hacia atrás para el cálculo RFM.

    Returns:
        DataFrame con una fila por cliente y columnas:
        - cliente_id
        - recency, frequency, monetary, dias_entre_compras
        - es_single_buyer
        - cluster_id (0-4)
        - segmento_cluster (nombre de negocio: "MVPs", "Hibernando", etc.)
        - distancia_propia, distancia_segunda, razon_distancias, segmento_secundario
          (señales de "frontera" entre clusters, ver _agregar_distancias_frontera)
    """
    # 1. Calcular features RFM (incluye imputación de single-buyers)
    df_rfm = calcular_rfm_completo(
        df_orders,
        fecha_ref=fecha_ref,
        ventana_meses=ventana_meses,
    )

    # 2. Cargar el modelo congelado
    log.info("Cargando modelo de segmentación versión '%s'", model_version)
    seg = SegmentadorClientes.load(version=model_version)
    log.info("Modelo cargado: %s", seg)

    # 3. Aplicar la segmentación
    df_segmentado = seg.predict(df_rfm)

    # 3b. Distancias a centroides (señales de transición para la vista Movimientos)
    _agregar_distancias_frontera(df_segmentado, seg)

    # 4. Reporte de distribución
    log.info("Distribución de segmentos:")
    for segmento, n in df_segmentado["segmento_cluster"].value_counts().items():
        pct = n / len(df_segmentado) * 100
        log.info("  %-12s %s (%.1f%%)", segmento, f"{n:,}", pct)

    return df_segmentado


def _agregar_distancias_frontera(
    df_segmentado: pd.DataFrame,
    seg: SegmentadorClientes,
) -> None:
    """Anexa in-place las señales de frontera entre clusters.

    Replica los pasos del pipeline previos a K-Means (log1p → scaler) sobre las
    features en escala original para obtener el espacio escalado donde viven los
    centroides, y calcula la distancia de cada cliente a TODOS los centroides.

    Columnas agregadas:
        - distancia_propia    : distancia al centroide más cercano (= el asignado).
        - distancia_segunda   : distancia al segundo centroide más cercano.
        - razon_distancias    : distancia_propia / distancia_segunda ∈ [0, 1].
                                Cerca de 1 ⇒ cliente "en frontera" (ambiguo).
        - segmento_secundario : nombre del segundo cluster más cercano.
    """
    # Features en el espacio escalado donde viven los centroides (el segmentador
    # es dueño del pipeline; no replicamos sus pasos internos aquí).
    X_transformed = seg.transform_features(df_segmentado)

    centroides = seg.pipeline.named_steps["kmeans"].cluster_centers_
    distancias = np.linalg.norm(
        X_transformed[:, np.newaxis, :] - centroides[np.newaxis, :, :],
        axis=2,
    )  # (n_clientes, k)

    orden = np.argsort(distancias, axis=1)
    filas = np.arange(len(distancias))
    dist_propia = distancias[filas, orden[:, 0]]
    dist_segunda = distancias[filas, orden[:, 1]]
    seg_secundario_idx = orden[:, 1]

    nombres = seg.cluster_names_ordered
    df_segmentado["distancia_propia"] = dist_propia
    df_segmentado["distancia_segunda"] = dist_segunda
    df_segmentado["razon_distancias"] = dist_propia / dist_segunda
    df_segmentado["segmento_secundario"] = [nombres[i] for i in seg_secundario_idx]