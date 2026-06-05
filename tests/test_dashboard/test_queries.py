"""Tests de las funciones puras de queries.py (SPEC v2).

Llaman a las funciones directamente: get_connection() registra las vistas de
forma perezosa, así que no requieren el lifespan del TestClient. El fixture
`cliente_real` (conftest) provee un cliente_id existente en la base.
"""
from __future__ import annotations

import math

from pulse.dashboard.queries import (
    cliente_bundles_propios,
    cliente_oportunidades,
    cliente_productos_top,
    clientes_en_frontera,
    clientes_reactivacion,
    clientes_urgentes,
)


# ─────────────────────────────────────────────────────────────────────────────
# Cambio 1: tabs de alertas
# ─────────────────────────────────────────────────────────────────────────────

def test_clientes_urgentes_excluye_single_buyers() -> None:
    """clientes_urgentes() solo debe incluir MVPs / Alto Valor."""
    segmentos = {r["segmento"] for r in clientes_urgentes()}
    assert segmentos.issubset({"MVPs", "Alto Valor"})


def test_clientes_reactivacion_solo_en_riesgo() -> None:
    """clientes_reactivacion() solo debe incluir el segmento En Riesgo."""
    segmentos = {r["segmento"] for r in clientes_reactivacion()}
    assert segmentos == {"En Riesgo"} or len(segmentos) == 0


def test_ratio_no_es_infinito() -> None:
    """El ratio nunca debe ser None ni infinito (GREATEST garantiza esto)."""
    for fn in (clientes_urgentes, clientes_reactivacion):
        for r in fn():
            assert r["ratio"] is not None
            assert math.isfinite(r["ratio"])


# ─────────────────────────────────────────────────────────────────────────────
# Cambio 2: drill-down enriquecido (productos + bundles propios + oportunidades)
# ─────────────────────────────────────────────────────────────────────────────

def test_cliente_productos_top_excluye_cargo(cliente_real: str) -> None:
    """cliente_productos_top() no debe incluir filas con clave CARGO100."""
    rows = cliente_productos_top(cliente_real, limit=10)
    assert all(r["familia"] is not None for r in rows)
    assert not any("CARGO" in r["familia"] for r in rows)


def test_cliente_bundles_propios_orden_lexicografico(cliente_real: str) -> None:
    """En cada par, familia_a < familia_b (normalización lexicográfica)."""
    for r in cliente_bundles_propios(cliente_real, limit=10):
        assert r["familia_a"] < r["familia_b"]
        # pct_aparicion es una proporción válida
        assert 0.0 <= r["pct_aparicion"] <= 1.0


def test_cliente_oportunidades_estructura(cliente_real: str) -> None:
    """Cada oportunidad indica qué compró y qué le faltó (distintos)."""
    for r in cliente_oportunidades(cliente_real, limit=10):
        assert "compro" in r and "le_falto" in r
        assert r["compro"] != r["le_falto"]


# ─────────────────────────────────────────────────────────────────────────────
# Cambio 3: Movimientos
# ─────────────────────────────────────────────────────────────────────────────

def test_clientes_en_frontera_threshold() -> None:
    """Todo cliente devuelto supera el threshold de razón de distancias."""
    rows = clientes_en_frontera(threshold=0.7)
    for r in rows:
        assert r["razon_distancias"] >= 0.7
        assert r["es_single_buyer"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints API
# ─────────────────────────────────────────────────────────────────────────────

def test_api_alertas_urgentes(client) -> None:
    r = client.get("/api/alertas/urgentes")
    assert r.status_code == 200
    d = r.json()
    assert "kpis" in d and "clientes" in d
    assert {row["segmento"] for row in d["clientes"]}.issubset({"MVPs", "Alto Valor"})


def test_api_alertas_reactivacion(client) -> None:
    r = client.get("/api/alertas/reactivacion")
    assert r.status_code == 200
    d = r.json()
    assert "kpis" in d and "clientes" in d
    segmentos = {row["segmento"] for row in d["clientes"]}
    assert segmentos == {"En Riesgo"} or len(segmentos) == 0


def test_api_cliente_incluye_bundles_y_oportunidades(client, cliente_real: str) -> None:
    d = client.get(f"/api/cliente/{cliente_real}").json()
    assert "productos_top" in d
    assert "bundles_propios" in d
    assert "oportunidades" in d
    assert isinstance(d["bundles_propios"], list)
    assert isinstance(d["oportunidades"], list)


def test_api_movimientos(client) -> None:
    r = client.get("/api/movimientos")
    assert r.status_code == 200
    d = r.json()
    for key in ["n_en_frontera", "n_subidas_mes", "n_bajadas_mes", "n_total_cambios"]:
        assert key in d["kpis"]
    assert isinstance(d["frontera"], list)
    assert isinstance(d["cambios"], list)
    # Coherencia: el KPI de frontera coincide con el largo de la tabla frontera.
    assert d["kpis"]["n_en_frontera"] == len(d["frontera"])


# ─────────────────────────────────────────────────────────────────────────────
# Consistencia de moneda: revenue_total (subtotal_mxn) vs monetary RFM
# ─────────────────────────────────────────────────────────────────────────────

def test_revenue_total_suma_a_monetary():
    """La suma de revenue_total de TODAS las familias de un cliente debe
    coincidir con su monetary RFM (dentro de un margen de redondeo).

    Si no coincide, hay un bug de moneda o un filtro inconsistente entre
    items y orders.
    """
    from pulse.dashboard.queries import cliente_productos_top, cliente_perfil

    # Cliente de prueba con compras en USD (caso problemático histórico)
    cliente_id = "PAC0751"
    productos = cliente_productos_top(cliente_id, limit=999)  # sin límite efectivo
    perfil = cliente_perfil(cliente_id)

    suma_revenue = sum(p["revenue_total"] for p in productos)
    monetary = perfil["monetary"]

    # Tolerancia: 5% por diferencias legítimas entre pago_total (incluye IVA,
    # cargos extra) y subtotal_mxn (solo productos). Si la diferencia es mayor,
    # algo está mal estructuralmente.
    diferencia_pct = abs(suma_revenue - monetary) / monetary
    assert diferencia_pct < 0.05, (
        f"Suma de revenue ({suma_revenue:,.0f}) no coincide con monetary "
        f"({monetary:,.0f}). Diferencia: {diferencia_pct:.1%}"
    )


def test_revenue_total_no_es_subestimado_para_usd():
    """Verificación específica: clientes con catálogo principalmente USD
    deben mostrar revenue en órdenes de magnitud razonables vs su monetary.

    Antes del fix, PAC0751 mostraba $1.06M en revenue cuando su monetary
    real era $8.93M (factor ~8x por no convertir USD).
    """
    from pulse.dashboard.queries import cliente_productos_top, cliente_perfil

    cliente_id = "PAC0751"
    productos = cliente_productos_top(cliente_id, limit=999)
    perfil = cliente_perfil(cliente_id)

    suma_revenue = sum(p["revenue_total"] for p in productos)
    monetary = perfil["monetary"]

    # Después del fix, la suma de revenue debe ser al menos el 50% del
    # monetary (sería 100% si no hubiera IVA ni cargos extra).
    assert suma_revenue / monetary > 0.5, (
        f"Revenue ({suma_revenue:,.0f}) es menos del 50% del monetary "
        f"({monetary:,.0f}). Probablemente las queries siguen usando "
        f"precio_final sin normalizar."
    )
