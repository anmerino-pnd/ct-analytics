"""
Tests para pulse.pipeline.validacion.

Cubre:
1. Validar ingest detecta caídas grandes y permite primera corrida.
2. Validar clientes detecta nulos y rangos inválidos.
3. Validar distribución cacha concentración anormal en un cluster.
4. Cross-check temporalidad vs RFM.

Ejecutar con: pytest tests/test_validacion.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from pulse.pipeline.validacion import (
    QualityCheckFailed,
    validar_clientes_segmentados,
    validar_distribucion_segmentos,
    validar_ingest,
    validar_temporalidad_mensual,
)


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------
@pytest.fixture
def df_clientes_sanos() -> pd.DataFrame:
    """100 clientes balanceados entre 5 segmentos, sin nulos."""
    segmentos = ["MVPs", "Alto Valor", "Ocasionales", "En Riesgo", "Hibernando"]
    return pd.DataFrame([
        {
            "cliente_id": f"C{i:04d}",
            "recency": float(i + 1),
            "frequency": float(i + 1),
            "monetary": float((i + 1) * 100),
            "dias_entre_compras": float(i + 5),
            "es_single_buyer": 0,
            "cluster_id": i % 5,
            "segmento_cluster": segmentos[i % 5],
        }
        for i in range(100)
    ])


# ----------------------------------------------------------------
# validar_ingest
# ----------------------------------------------------------------
class TestValidarIngest:
    def test_pasa_si_no_hay_estado_previo(self):
        validar_ingest(n_orders_post=1000, n_orders_pre=None)  # no debe lanzar

    def test_pasa_si_orders_aumentan(self):
        validar_ingest(n_orders_post=1100, n_orders_pre=1000)

    def test_pasa_si_caida_es_pequena(self):
        # 2% de caída con umbral default 5%
        validar_ingest(n_orders_post=980, n_orders_pre=1000)

    def test_falla_si_caida_es_grande(self):
        # 20% de caída
        with pytest.raises(QualityCheckFailed, match="destruyó datos"):
            validar_ingest(n_orders_post=800, n_orders_pre=1000)


# ----------------------------------------------------------------
# validar_clientes_segmentados
# ----------------------------------------------------------------
class TestValidarClientes:
    def test_pasa_con_clientes_sanos(self, df_clientes_sanos):
        validar_clientes_segmentados(df_clientes_sanos)

    def test_falla_si_dataframe_vacio(self):
        df_vacio = pd.DataFrame(
            columns=["cliente_id", "segmento_cluster", "cluster_id",
                     "recency", "frequency", "monetary", "dias_entre_compras"]
        )
        with pytest.raises(QualityCheckFailed, match="vacío"):
            validar_clientes_segmentados(df_vacio)

    def test_falla_si_falta_segmento(self, df_clientes_sanos):
        df = df_clientes_sanos.copy()
        df.loc[0, "segmento_cluster"] = None
        with pytest.raises(QualityCheckFailed, match="sin segmento"):
            validar_clientes_segmentados(df)

    def test_falla_si_hay_nulos_en_features(self, df_clientes_sanos):
        df = df_clientes_sanos.copy()
        df.loc[0, "dias_entre_compras"] = None
        with pytest.raises(QualityCheckFailed, match="nulos en features"):
            validar_clientes_segmentados(df)

    def test_falla_si_cluster_id_fuera_de_rango(self, df_clientes_sanos):
        df = df_clientes_sanos.copy()
        df.loc[0, "cluster_id"] = 99
        with pytest.raises(QualityCheckFailed, match="fuera de rango"):
            validar_clientes_segmentados(df)


# ----------------------------------------------------------------
# validar_distribucion_segmentos
# ----------------------------------------------------------------
class TestValidarDistribucion:
    def test_pasa_con_distribucion_balanceada(self, df_clientes_sanos):
        validar_distribucion_segmentos(df_clientes_sanos)

    def test_falla_si_un_segmento_domina(self):
        # 80 de 100 en MVPs (80% > 50% default)
        df = pd.DataFrame([
            {"cliente_id": f"C{i:04d}",
             "segmento_cluster": "MVPs" if i < 80 else "Hibernando"}
            for i in range(100)
        ])
        with pytest.raises(QualityCheckFailed, match="absorbe"):
            validar_distribucion_segmentos(df)

    def test_umbral_configurable(self):
        # 30% en MVPs: falla con umbral 25%, pasa con default 50%
        df = pd.DataFrame([
            {"cliente_id": f"C{i:04d}",
             "segmento_cluster": "MVPs" if i < 30 else "Otros"}
            for i in range(100)
        ])
        validar_distribucion_segmentos(df, max_pct_un_segmento=80)  # pasa
        with pytest.raises(QualityCheckFailed):
            validar_distribucion_segmentos(df, max_pct_un_segmento=25)


# ----------------------------------------------------------------
# validar_temporalidad_mensual
# ----------------------------------------------------------------
class TestValidarTemporalidad:
    def test_pasa_si_pedidos_cuadran(self):
        df_mensual = pd.DataFrame([
            {"segmento_cluster": "MVPs", "año_mes": "2026-01", "pedidos": 100},
            {"segmento_cluster": "MVPs", "año_mes": "2026-02", "pedidos": 150},
        ])
        df_clientes = pd.DataFrame([{"frequency": 250}])  # suma exacta
        validar_temporalidad_mensual(df_mensual, df_clientes)

    def test_pasa_si_diferencia_es_pequena(self):
        df_mensual = pd.DataFrame([
            {"segmento_cluster": "MVPs", "año_mes": "2026-01", "pedidos": 99},
        ])
        df_clientes = pd.DataFrame([{"frequency": 100}])  # 1% diferencia
        validar_temporalidad_mensual(df_mensual, df_clientes)

    def test_falla_si_diferencia_es_grande(self):
        df_mensual = pd.DataFrame([
            {"segmento_cluster": "MVPs", "año_mes": "2026-01", "pedidos": 50},
        ])
        df_clientes = pd.DataFrame([{"frequency": 100}])  # 50% diferencia
        with pytest.raises(QualityCheckFailed, match="Inconsistencia"):
            validar_temporalidad_mensual(df_mensual, df_clientes)

    def test_salta_si_mensual_vacio(self):
        df_clientes = pd.DataFrame([{"frequency": 100}])
        validar_temporalidad_mensual(pd.DataFrame(), df_clientes)  # no lanza