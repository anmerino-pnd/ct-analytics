"""
Tests para pulse.analytics.rfm.

Cubre:
1. Cálculo correcto de recency, frequency, monetary, cadencia.
2. Imputación de single-buyers (NaN → p95 + flag).
3. Filtro por ventana temporal.
4. Fecha de referencia configurable.
5. Validación de input.

Ejecutar con: pytest tests/test_rfm.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from pulse.analytics.rfm import calcular_rfm_completo


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------
@pytest.fixture
def fecha_ref() -> datetime:
    """Fecha de referencia fija para tests reproducibles."""
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def df_orders_simple(fecha_ref) -> pd.DataFrame:
    """
    3 clientes con comportamientos distintos:
    - C001 (MVP-like): 4 compras recientes, cadencia ~30 días, alto monto.
    - C002 (En riesgo): 3 compras pero la última hace 200 días.
    - C003 (Single-buyer): 1 sola compra reciente.
    """
    return pd.DataFrame([
        # C001: comprador frecuente
        {"cliente_id": "C001", "fecha": fecha_ref - timedelta(days=10),  "pago_total": 5000},
        {"cliente_id": "C001", "fecha": fecha_ref - timedelta(days=40),  "pago_total": 4500},
        {"cliente_id": "C001", "fecha": fecha_ref - timedelta(days=70),  "pago_total": 6000},
        {"cliente_id": "C001", "fecha": fecha_ref - timedelta(days=100), "pago_total": 5500},
        # C002: enfriándose
        {"cliente_id": "C002", "fecha": fecha_ref - timedelta(days=200), "pago_total": 2000},
        {"cliente_id": "C002", "fecha": fecha_ref - timedelta(days=260), "pago_total": 1800},
        {"cliente_id": "C002", "fecha": fecha_ref - timedelta(days=320), "pago_total": 2200},
        # C003: single-buyer
        {"cliente_id": "C003", "fecha": fecha_ref - timedelta(days=30),  "pago_total": 1500},
    ])


# ----------------------------------------------------------------
# Tests de cálculo de features
# ----------------------------------------------------------------
class TestCalculoFeatures:
    def test_retorna_columnas_esperadas(self, df_orders_simple, fecha_ref):
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        cols = {"cliente_id", "recency", "frequency", "monetary",
                "dias_entre_compras", "es_single_buyer"}
        assert cols.issubset(rfm.columns)

    def test_un_cliente_por_fila(self, df_orders_simple, fecha_ref):
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        assert rfm["cliente_id"].is_unique
        assert len(rfm) == 3

    def test_recency_correcta(self, df_orders_simple, fecha_ref):
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        rfm = rfm.set_index("cliente_id")
        assert rfm.loc["C001", "recency"] == 10
        assert rfm.loc["C002", "recency"] == 200
        assert rfm.loc["C003", "recency"] == 30

    def test_frequency_correcta(self, df_orders_simple, fecha_ref):
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        rfm = rfm.set_index("cliente_id")
        assert rfm.loc["C001", "frequency"] == 4
        assert rfm.loc["C002", "frequency"] == 3
        assert rfm.loc["C003", "frequency"] == 1

    def test_monetary_correcta(self, df_orders_simple, fecha_ref):
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        rfm = rfm.set_index("cliente_id")
        assert rfm.loc["C001", "monetary"] == 5000 + 4500 + 6000 + 5500
        assert rfm.loc["C002", "monetary"] == 2000 + 1800 + 2200
        assert rfm.loc["C003", "monetary"] == 1500

    def test_cadencia_es_mediana_de_diferencias(self, df_orders_simple, fecha_ref):
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        rfm = rfm.set_index("cliente_id")
        # C001: compras a -100, -70, -40, -10 → diffs = [30, 30, 30] → mediana = 30
        assert rfm.loc["C001", "dias_entre_compras"] == 30


# ----------------------------------------------------------------
# Tests de imputación de single-buyers
# ----------------------------------------------------------------
class TestImputacionSingleBuyers:
    def test_single_buyer_recibe_flag(self, df_orders_simple, fecha_ref):
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        rfm = rfm.set_index("cliente_id")
        assert rfm.loc["C003", "es_single_buyer"] == 1
        assert rfm.loc["C001", "es_single_buyer"] == 0

    def test_single_buyer_cadencia_imputada(self, df_orders_simple, fecha_ref):
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        rfm = rfm.set_index("cliente_id")
        # No debe quedar NaN tras la imputación
        assert not pd.isna(rfm.loc["C003", "dias_entre_compras"])
        # La cadencia imputada debe ser el p95 de los recurrentes
        assert rfm.loc["C003", "dias_entre_compras"] > 0

    def test_no_quedan_nulos_post_imputacion(self, df_orders_simple, fecha_ref):
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        features = ["recency", "frequency", "monetary", "dias_entre_compras"]
        assert rfm[features].isna().sum().sum() == 0

    def test_dataset_solo_single_buyers_usa_fallback(self, fecha_ref):
        """Caso límite: todos son single-buyers. Debe usar fallback, no fallar."""
        df = pd.DataFrame([
            {"cliente_id": "C001", "fecha": fecha_ref - timedelta(days=10), "pago_total": 100},
            {"cliente_id": "C002", "fecha": fecha_ref - timedelta(days=20), "pago_total": 200},
        ])
        rfm = calcular_rfm_completo(df, fecha_ref=fecha_ref)
        # Todos quedan como single-buyers
        assert (rfm["es_single_buyer"] == 1).all()
        # Y todos tienen la misma cadencia (la del fallback)
        assert rfm["dias_entre_compras"].nunique() == 1
        # Sin NaN
        assert not rfm.isna().any().any()


# ----------------------------------------------------------------
# Tests de ventana temporal
# ----------------------------------------------------------------
class TestVentanaTemporal:
    def test_excluye_pedidos_fuera_de_ventana(self, fecha_ref):
        # Cliente con 2 compras: una reciente (dentro), una de hace 5 años (fuera)
        df = pd.DataFrame([
            {"cliente_id": "C001", "fecha": fecha_ref - timedelta(days=30),   "pago_total": 1000},
            {"cliente_id": "C001", "fecha": fecha_ref - timedelta(days=1800), "pago_total": 2000},
        ])
        rfm = calcular_rfm_completo(df, fecha_ref=fecha_ref, ventana_meses=30)
        rfm = rfm.set_index("cliente_id")
        # Solo cuenta la compra reciente
        assert rfm.loc["C001", "frequency"] == 1
        assert rfm.loc["C001", "monetary"] == 1000
        # Por consecuencia, es single-buyer
        assert rfm.loc["C001", "es_single_buyer"] == 1

    def test_cliente_completamente_fuera_de_ventana_no_aparece(self, fecha_ref):
        df = pd.DataFrame([
            {"cliente_id": "C001", "fecha": fecha_ref - timedelta(days=30), "pago_total": 1000},
            {"cliente_id": "C002", "fecha": fecha_ref - timedelta(days=1800), "pago_total": 2000},
            # C002 está completamente fuera
            {"cliente_id": "C001", "fecha": fecha_ref - timedelta(days=60), "pago_total": 1500},
        ])
        rfm = calcular_rfm_completo(df, fecha_ref=fecha_ref, ventana_meses=30)
        assert "C002" not in rfm["cliente_id"].values
        assert "C001" in rfm["cliente_id"].values


# ----------------------------------------------------------------
# Tests de configurabilidad
# ----------------------------------------------------------------
class TestConfigurabilidad:
    def test_fecha_ref_naive_se_asume_utc(self, df_orders_simple):
        """Pasar fecha sin tzinfo no debe romper — debe asumirse UTC."""
        fecha_naive = datetime(2026, 1, 1)
        rfm = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_naive)
        assert len(rfm) == 3  # No falla

    def test_fecha_ref_distinta_cambia_recency(self, df_orders_simple, fecha_ref):
        rfm1 = calcular_rfm_completo(df_orders_simple, fecha_ref=fecha_ref)
        rfm2 = calcular_rfm_completo(
            df_orders_simple,
            fecha_ref=fecha_ref + timedelta(days=100),
        )
        # Recency debe haber aumentado 100 días para todos
        for cid in ["C001", "C002", "C003"]:
            r1 = rfm1.set_index("cliente_id").loc[cid, "recency"]
            r2 = rfm2.set_index("cliente_id").loc[cid, "recency"]
            assert r2 == r1 + 100


# ----------------------------------------------------------------
# Tests de validación
# ----------------------------------------------------------------
class TestValidacion:
    def test_falla_sin_columna_requerida(self, fecha_ref):
        df = pd.DataFrame({"cliente_id": ["C001"], "fecha": [fecha_ref]})
        # Falta pago_total
        with pytest.raises(ValueError, match="pago_total"):
            calcular_rfm_completo(df, fecha_ref=fecha_ref)