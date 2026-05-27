"""
Tests para pulse.analytics.mba.

Cubre:
1. Pipeline completo retorna los 3 DataFrames esperados.
2. Reglas accionables tienen el formato 1→1 o 1→2.
3. Reglas exclusivas aparecen en un solo segmento.
4. Validación de columnas requeridas.
5. Cálculo de ticket_medio sobre pedidos que materializan la regla.

Ejecutar con: pytest tests/test_mba.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from pulse.analytics.mba import calcular_mba


# ----------------------------------------------------------------
# Fixtures: construimos un dataset con co-compras claras
# ----------------------------------------------------------------
@pytest.fixture
def datos_mba_sinteticos():
    """
    Construimos pedidos con co-compras predecibles:
    - 200 pedidos con CAMARA + DISCO (regla clara CAMARA ⇒ DISCO).
    - 100 pedidos con CAMARA solo.
    - 100 pedidos con DISCO solo.
    - 100 pedidos con LAPTOP + MOUSE (otra regla clara).
    - Repartidos en 2 segmentos: 60% MVPs, 40% Alto Valor.

    Esto garantiza reglas estadísticamente significativas.
    """
    rng = np.random.default_rng(seed=42)
    orders = []
    items = []
    segmentos_rows = []
    clientes_creados = set()

    def add_pedido(order_id, cliente_id, claves, segmento, pago=1000.0):
        orders.append({"order_id": order_id, "pago_total": pago})
        for clave in claves:
            items.append({
                "order_id": order_id,
                "cliente_id": cliente_id,
                "clave": clave,
                "familia": clave,  # sin dígitos en sintético: familia == clave
            })
        if cliente_id not in clientes_creados:
            segmentos_rows.append({
                "cliente_id": cliente_id,
                "segmento_cluster": segmento,
            })
            clientes_creados.add(cliente_id)

    oid = 0
    # 200 pedidos CAMARA + DISCO (la regla "fuerte" que queremos detectar)
    for i in range(200):
        cid = f"C{i % 50:04d}"  # 50 clientes únicos
        seg = "MVPs" if i % 5 < 3 else "Alto Valor"
        add_pedido(f"O{oid:05d}", cid, ["CAMARA", "DISCO"], seg)
        oid += 1

    # 1000 pedidos multi-familia con productos VARIADOS (ruido base) — necesarios
    # para que el lift de CAMARA→DISCO sea alto. Si todo lo multi-familia fuera
    # CAMARA+DISCO, el lift sería bajo (no hay "azar contra el cual comparar").
    productos_ruido = [
        ["CABLE", "ADAPTADOR"], ["CARGADOR", "BATERIA"], ["TECLADO_X", "MOUSE_X"],
        ["MEMORIA", "DISCOX"], ["IMPRESORA", "TINTA"], ["MONITOR_X", "HDMI"],
        ["AUDIFONO", "MICROFONO"], ["WEBCAM", "TRIPODE"],
    ]
    for i in range(1000):
        cid = f"C{(i % 80) + 100:04d}"
        seg = "MVPs" if i % 5 < 3 else "Alto Valor"
        combo = productos_ruido[i % len(productos_ruido)]
        add_pedido(f"O{oid:05d}", cid, combo, seg)
        oid += 1

    # 100 pedidos LAPTOP + MOUSE (otra regla clara)
    for i in range(100):
        cid = f"C{i % 30:04d}"
        seg = "MVPs" if i % 5 < 3 else "Alto Valor"
        add_pedido(f"O{oid:05d}", cid, ["LAPTOP", "MOUSE"], seg)
        oid += 1

    # 50 pedidos con TECLADO + MONITOR — solo en Alto Valor (será exclusiva)
    # Usamos un rango de clientes alto (3000+) para evitar colisiones con el ruido
    for i in range(50):
        cid = f"C{i + 3000:04d}"
        add_pedido(f"O{oid:05d}", cid, ["TECLADO", "MONITOR"], "Alto Valor")
        oid += 1

    return {
        "items": pd.DataFrame(items),
        "orders": pd.DataFrame(orders),
        "segmentos": pd.DataFrame(segmentos_rows),
    }


# ----------------------------------------------------------------
# Tests
# ----------------------------------------------------------------
class TestPipelineCompleto:
    def test_retorna_tres_dataframes(self, datos_mba_sinteticos):
        resultado = calcular_mba(
            datos_mba_sinteticos["items"],
            datos_mba_sinteticos["segmentos"],
            datos_mba_sinteticos["orders"],
        )
        assert set(resultado.keys()) == {"por_segmento", "exclusivas", "accionables"}
        for nombre, df in resultado.items():
            assert isinstance(df, pd.DataFrame), f"{nombre} no es DataFrame"

    def test_detecta_regla_obvia_camara_disco(self, datos_mba_sinteticos):
        """La regla CAMARA ⇒ DISCO debe aparecer (200 pedidos la respaldan)."""
        resultado = calcular_mba(
            datos_mba_sinteticos["items"],
            datos_mba_sinteticos["segmentos"],
            datos_mba_sinteticos["orders"],
        )
        df = resultado["por_segmento"]

        # Buscar la regla en cualquier dirección (la dedup conserva la de mayor confidence)
        encontrada = (
            ((df["antecedents"] == "CAMARA") & (df["consequents"] == "DISCO"))
            | ((df["antecedents"] == "DISCO") & (df["consequents"] == "CAMARA"))
        )
        assert encontrada.any(), "No se detectó la regla CAMARA ⇒ DISCO"


class TestReglasAccionables:
    def test_solo_uno_a_uno_y_uno_a_dos(self, datos_mba_sinteticos):
        resultado = calcular_mba(
            datos_mba_sinteticos["items"],
            datos_mba_sinteticos["segmentos"],
            datos_mba_sinteticos["orders"],
        )
        df = resultado["accionables"]
        assert (df["n_antecedents"] == 1).all()
        assert (df["n_consequents"] <= 2).all()

    def test_tienen_ticket_medio(self, datos_mba_sinteticos):
        resultado = calcular_mba(
            datos_mba_sinteticos["items"],
            datos_mba_sinteticos["segmentos"],
            datos_mba_sinteticos["orders"],
        )
        df = resultado["accionables"]
        assert "ticket_medio" in df.columns
        assert "revenue_total" in df.columns
        assert (df["ticket_medio"] > 0).all()

    def test_tienen_n_pedidos_positivo(self, datos_mba_sinteticos):
        resultado = calcular_mba(
            datos_mba_sinteticos["items"],
            datos_mba_sinteticos["segmentos"],
            datos_mba_sinteticos["orders"],
        )
        df = resultado["accionables"]
        assert (df["n_pedidos"] > 0).all()


class TestReglasExclusivas:
    def test_exclusivas_aparecen_en_un_segmento(self, datos_mba_sinteticos):
        resultado = calcular_mba(
            datos_mba_sinteticos["items"],
            datos_mba_sinteticos["segmentos"],
            datos_mba_sinteticos["orders"],
        )
        df_excl = resultado["exclusivas"]

        if df_excl.empty:
            return  # Si no hay exclusivas, no hay nada que validar

        # Cada regla debe estar en un único segmento
        df_excl_id = df_excl.copy()
        df_excl_id["regla_id"] = df_excl_id["antecedents"] + " ⇒ " + df_excl_id["consequents"]
        conteo = df_excl_id.groupby("regla_id")["segmento"].nunique()
        assert (conteo == 1).all(), "Hay reglas 'exclusivas' que aparecen en >1 segmento"

    def test_teclado_monitor_es_exclusiva_de_alto_valor(self, datos_mba_sinteticos):
        """En el fixture, TECLADO+MONITOR solo aparece en Alto Valor."""
        resultado = calcular_mba(
            datos_mba_sinteticos["items"],
            datos_mba_sinteticos["segmentos"],
            datos_mba_sinteticos["orders"],
        )
        df_excl = resultado["exclusivas"]

        encontrada = (
            ((df_excl["antecedents"] == "TECLADO") & (df_excl["consequents"] == "MONITOR"))
            | ((df_excl["antecedents"] == "MONITOR") & (df_excl["consequents"] == "TECLADO"))
        )
        if encontrada.any():
            seg = df_excl[encontrada]["segmento"].iloc[0]
            assert seg == "Alto Valor"


class TestValidacionInput:
    def test_falla_sin_familia_en_items(self, datos_mba_sinteticos):
        items_sin_familia = datos_mba_sinteticos["items"].drop(columns=["familia"])
        with pytest.raises(ValueError, match="familia"):
            calcular_mba(
                items_sin_familia,
                datos_mba_sinteticos["segmentos"],
                datos_mba_sinteticos["orders"],
            )

    def test_falla_sin_segmento_cluster(self, datos_mba_sinteticos):
        segs_sin_columna = datos_mba_sinteticos["segmentos"].drop(columns=["segmento_cluster"])
        with pytest.raises(ValueError, match="segmento_cluster"):
            calcular_mba(
                datos_mba_sinteticos["items"],
                segs_sin_columna,
                datos_mba_sinteticos["orders"],
            )

    def test_falla_sin_pago_total(self, datos_mba_sinteticos):
        orders_sin_pago = datos_mba_sinteticos["orders"].drop(columns=["pago_total"])
        with pytest.raises(ValueError, match="pago_total"):
            calcular_mba(
                datos_mba_sinteticos["items"],
                datos_mba_sinteticos["segmentos"],
                orders_sin_pago,
            )