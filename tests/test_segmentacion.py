"""
Tests para pulse.analytics.segmentacion.

Como segmentar_clientes() llama a SegmentadorClientes.load() sin parámetro
models_dir, el test entrena un modelo en un directorio temporal y parchea
el método .load para que apunte a ese directorio.

Ejecutar con: pytest tests/test_segmentacion.py -v
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from pulse.analytics.segmentacion import segmentar_clientes
from pulse.modeling.segmentador import SegmentadorClientes, build_pipeline


# Guardamos referencia al método original ANTES de cualquier patch
_LOAD_ORIGINAL = SegmentadorClientes.load


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------
@pytest.fixture
def fecha_ref() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def df_orders_sinteticos(fecha_ref) -> pd.DataFrame:
    """300 clientes sintéticos suficientes para entrenar K-Means de 5 clusters."""
    rng = np.random.default_rng(seed=42)
    rows = []
    for i in range(300):
        cliente_id = f"C{i:04d}"
        n_compras = rng.integers(1, 11)
        for _ in range(n_compras):
            dias_atras = rng.integers(1, 700)
            rows.append({
                "cliente_id": cliente_id,
                "fecha": fecha_ref - timedelta(days=int(dias_atras)),
                "pago_total": float(rng.uniform(100, 50000)),
            })
    return pd.DataFrame(rows)


@pytest.fixture
def modelo_dummy_dir(df_orders_sinteticos, fecha_ref):
    """Entrena un modelo dummy y lo guarda en dir temporal. Yield el path."""
    from pulse.analytics.rfm import calcular_rfm_completo

    df_rfm = calcular_rfm_completo(df_orders_sinteticos, fecha_ref=fecha_ref)
    features = ["recency", "frequency", "monetary", "dias_entre_compras"]

    pipeline = build_pipeline()
    pipeline.fit(df_rfm[features])

    seg = SegmentadorClientes.from_fitted(
        pipeline=pipeline,
        version="v1",
        features=features,
        cluster_names={i: f"Grupo{i}" for i in range(5)},
        n_clientes_entrenamiento=len(df_rfm),
    )

    with tempfile.TemporaryDirectory() as d:
        seg.save(models_dir=d)
        yield Path(d)


@pytest.fixture
def segmentador_apuntando_a_dummy(modelo_dummy_dir):
    """
    Context manager que parchea load() para que use el directorio dummy.
    Llama al método original guardado al inicio del archivo (no a SegmentadorClientes.load
    actual, que podría estar parcheado).
    """
    def load_redirigido(version, models_dir=None):
        return _LOAD_ORIGINAL(version=version, models_dir=modelo_dummy_dir)

    with patch.object(SegmentadorClientes, "load", side_effect=load_redirigido):
        yield


# ----------------------------------------------------------------
# Tests
# ----------------------------------------------------------------
class TestSegmentarClientes:
    def test_pipeline_retorna_columnas_esperadas(
        self, df_orders_sinteticos, fecha_ref, segmentador_apuntando_a_dummy
    ):
        df_seg = segmentar_clientes(df_orders_sinteticos, fecha_ref=fecha_ref)

        cols_esperadas = {
            "cliente_id", "recency", "frequency", "monetary",
            "dias_entre_compras", "es_single_buyer",
            "cluster_id", "segmento_cluster",
        }
        assert cols_esperadas.issubset(df_seg.columns)

    def test_un_cliente_por_fila(
        self, df_orders_sinteticos, fecha_ref, segmentador_apuntando_a_dummy
    ):
        df_seg = segmentar_clientes(df_orders_sinteticos, fecha_ref=fecha_ref)
        assert df_seg["cliente_id"].is_unique

    def test_todos_reciben_segmento(
        self, df_orders_sinteticos, fecha_ref, segmentador_apuntando_a_dummy
    ):
        df_seg = segmentar_clientes(df_orders_sinteticos, fecha_ref=fecha_ref)
        assert df_seg["segmento_cluster"].notna().all()
        assert df_seg["cluster_id"].notna().all()

    def test_cluster_id_en_rango_valido(
        self, df_orders_sinteticos, fecha_ref, segmentador_apuntando_a_dummy
    ):
        df_seg = segmentar_clientes(df_orders_sinteticos, fecha_ref=fecha_ref)
        assert df_seg["cluster_id"].between(0, 4).all()

    def test_resultado_deterministico(
        self, df_orders_sinteticos, fecha_ref, segmentador_apuntando_a_dummy
    ):
        df1 = segmentar_clientes(df_orders_sinteticos, fecha_ref=fecha_ref)
        df2 = segmentar_clientes(df_orders_sinteticos, fecha_ref=fecha_ref)
        df1 = df1.sort_values("cliente_id").reset_index(drop=True)
        df2 = df2.sort_values("cliente_id").reset_index(drop=True)
        pd.testing.assert_series_equal(df1["cluster_id"], df2["cluster_id"])

    def test_agrega_columnas_de_distancia(
        self, df_orders_sinteticos, fecha_ref, segmentador_apuntando_a_dummy
    ):
        """segmentar_clientes() debe anexar las 4 señales de frontera."""
        df_seg = segmentar_clientes(df_orders_sinteticos, fecha_ref=fecha_ref)
        for col in ["distancia_propia", "distancia_segunda",
                    "razon_distancias", "segmento_secundario"]:
            assert col in df_seg.columns
        # razon = propia/segunda, y propia <= segunda ⇒ razón ∈ [0, 1].
        assert (df_seg["razon_distancias"] >= 0).all()
        assert (df_seg["razon_distancias"] <= 1.0001).all()
        # El segmento secundario es uno de los nombres de cluster válidos.
        nombres = set(df_seg["segmento_cluster"].unique())
        assert set(df_seg["segmento_secundario"].unique()).issubset(nombres)