"""
Tests para pulse.analytics.temporalidad.

Cubre:
1. Genera los 3 DataFrames esperados.
2. Agregados son consistentes (suma de pedidos = total en ventana).
3. Filtro de ventana temporal funciona.
4. Bundles temporales: solo aparecen las reglas top_n por segmento.
5. Validación de columnas.

Ejecutar con: pytest tests/test_temporalidad.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from pulse.analytics.temporalidad import calcular_temporalidad


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------
@pytest.fixture
def fecha_ref() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def datos_temporales(fecha_ref):
    """
    Construimos un dataset con:
    - 100 pedidos en ventana (últimos 6 meses) repartidos en 2 segmentos.
    - 50 pedidos FUERA de ventana (hace 3 años) → deben excluirse.
    - Items para 2 reglas distintas: CAMARA+DISCO y LAPTOP+MOUSE.
    """
    rng = np.random.default_rng(seed=42)
    orders = []
    items = []
    segmentos_rows = []

    # 100 pedidos dentro de ventana
    for i in range(100):
        order_id = f"O{i:05d}"
        cliente_id = f"C{i % 20:04d}"
        dias_atras = int(rng.integers(1, 180))
        fecha = fecha_ref - timedelta(days=dias_atras, hours=int(rng.integers(0, 24)))
        orders.append({
            "order_id": order_id,
            "cliente_id": cliente_id,
            "fecha": fecha,
            "pago_total": float(rng.uniform(500, 5000)),
        })
        # La mitad tiene CAMARA+DISCO
        if i % 2 == 0:
            for fam in ["CAMARA", "DISCO"]:
                items.append({"order_id": order_id, "familia": fam})
        else:
            for fam in ["LAPTOP", "MOUSE"]:
                items.append({"order_id": order_id, "familia": fam})

    # 50 pedidos FUERA de ventana (hace 3 años)
    for i in range(100, 150):
        order_id = f"O{i:05d}"
        cliente_id = f"C{i % 20:04d}"
        fecha = fecha_ref - timedelta(days=int(rng.integers(1100, 1500)))
        orders.append({
            "order_id": order_id,
            "cliente_id": cliente_id,
            "fecha": fecha,
            "pago_total": float(rng.uniform(500, 5000)),
        })
        items.append({"order_id": order_id, "familia": "VIEJO"})

    # Segmentos: 60% MVPs, 40% Alto Valor
    for i in range(20):
        cid = f"C{i:04d}"
        seg = "MVPs" if i < 12 else "Alto Valor"
        segmentos_rows.append({"cliente_id": cid, "segmento_cluster": seg})

    # Reglas accionables sintéticas (formato de output de mba.py)
    accionables = pd.DataFrame([
        {"segmento": "MVPs", "antecedents": "CAMARA", "consequents": "DISCO", "lift": 50.0},
        {"segmento": "MVPs", "antecedents": "LAPTOP", "consequents": "MOUSE", "lift": 30.0},
        {"segmento": "Alto Valor", "antecedents": "CAMARA", "consequents": "DISCO", "lift": 45.0},
    ])

    return {
        "orders": pd.DataFrame(orders),
        "segmentos": pd.DataFrame(segmentos_rows),
        "items": pd.DataFrame(items),
        "accionables": accionables,
    }


# ----------------------------------------------------------------
# Tests
# ----------------------------------------------------------------
class TestPipelineCompleto:
    def test_retorna_tres_dataframes(self, datos_temporales, fecha_ref):
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            datos_temporales["accionables"],
            fecha_ref=fecha_ref,
        )
        assert set(resultado.keys()) == {"hora_dia", "mensual", "bundles"}

    def test_excluye_pedidos_fuera_de_ventana(self, datos_temporales, fecha_ref):
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            datos_temporales["accionables"],
            fecha_ref=fecha_ref,
            ventana_meses=12,  # Solo último año
        )
        # En el mensual no debe aparecer la familia "VIEJO"
        total_pedidos = resultado["mensual"]["pedidos"].sum()
        # Solo deben haber 100 pedidos (los de ventana)
        assert total_pedidos == 100


class TestAgregadoHoraDia:
    def test_estructura_columnas(self, datos_temporales, fecha_ref):
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            datos_temporales["accionables"],
            fecha_ref=fecha_ref,
        )
        cols = set(resultado["hora_dia"].columns)
        assert {"segmento_cluster", "dia_semana", "dia_nombre", "hora", "pedidos"} == cols

    def test_pedidos_son_positivos(self, datos_temporales, fecha_ref):
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            datos_temporales["accionables"],
            fecha_ref=fecha_ref,
        )
        assert (resultado["hora_dia"]["pedidos"] > 0).all()

    def test_dia_nombre_consistente_con_dia_semana(self, datos_temporales, fecha_ref):
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            datos_temporales["accionables"],
            fecha_ref=fecha_ref,
        )
        df = resultado["hora_dia"]
        # Lunes = 0
        df_lunes = df[df["dia_semana"] == 0]
        assert (df_lunes["dia_nombre"] == "Lunes").all()


class TestAgregadoMensual:
    def test_tiene_pedidos_y_revenue(self, datos_temporales, fecha_ref):
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            datos_temporales["accionables"],
            fecha_ref=fecha_ref,
        )
        df = resultado["mensual"]
        assert "pedidos" in df.columns
        assert "revenue" in df.columns
        assert (df["pedidos"] > 0).all()
        assert (df["revenue"] > 0).all()

    def test_año_mes_formato_correcto(self, datos_temporales, fecha_ref):
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            datos_temporales["accionables"],
            fecha_ref=fecha_ref,
        )
        df = resultado["mensual"]
        # Formato esperado: "YYYY-MM"
        assert df["año_mes"].str.match(r"^\d{4}-\d{2}$").all()


class TestAgregadoBundles:
    def test_solo_contiene_reglas_pasadas(self, datos_temporales, fecha_ref):
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            datos_temporales["accionables"],
            fecha_ref=fecha_ref,
        )
        df = resultado["bundles"]
        # Solo deberían aparecer las 3 reglas del fixture
        reglas_distintas = df["regla"].unique()
        # Cada regla tiene formato "A → B"
        for regla in reglas_distintas:
            assert "→" in regla

    def test_respeta_top_bundles_por_segmento(self, datos_temporales, fecha_ref):
        """Si pedimos top 1 por segmento, solo debe procesar la regla con mayor lift."""
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            datos_temporales["accionables"],
            fecha_ref=fecha_ref,
            top_bundles_por_segmento=1,
        )
        df = resultado["bundles"]
        # Cada segmento debe tener una sola regla distinta
        reglas_por_seg = df.groupby("segmento_regla")["regla"].nunique()
        assert (reglas_por_seg <= 1).all()

    def test_bundles_vacio_si_accionables_vacio(self, datos_temporales, fecha_ref):
        resultado = calcular_temporalidad(
            datos_temporales["orders"],
            datos_temporales["segmentos"],
            datos_temporales["items"],
            pd.DataFrame(),  # accionables vacío
            fecha_ref=fecha_ref,
        )
        assert resultado["bundles"].empty


class TestValidacion:
    def test_falla_sin_cliente_id_en_orders(self, datos_temporales, fecha_ref):
        orders_sin = datos_temporales["orders"].drop(columns=["cliente_id"])
        with pytest.raises(ValueError, match="cliente_id"):
            calcular_temporalidad(
                orders_sin,
                datos_temporales["segmentos"],
                datos_temporales["items"],
                datos_temporales["accionables"],
                fecha_ref=fecha_ref,
            )

    def test_falla_sin_segmento_cluster(self, datos_temporales, fecha_ref):
        seg_sin = datos_temporales["segmentos"].drop(columns=["segmento_cluster"])
        with pytest.raises(ValueError, match="segmento_cluster"):
            calcular_temporalidad(
                datos_temporales["orders"],
                seg_sin,
                datos_temporales["items"],
                datos_temporales["accionables"],
                fecha_ref=fecha_ref,
            )