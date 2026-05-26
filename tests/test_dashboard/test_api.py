"""Tests de los endpoints JSON del dashboard.

Mínimo 2 tests por endpoint: happy path + edge case (404, params inválidos, etc.).
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# /api/segmentos/distribucion
# ─────────────────────────────────────────────────────────────────────────────

def test_distribucion_devuelve_5_segmentos(client) -> None:
    r = client.get("/api/segmentos/distribucion")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 5
    assert all("segmento" in row and "n_clientes" in row for row in data)


def test_distribucion_suma_total_clientes_consistente(client) -> None:
    """La suma por segmento debe coincidir con n_clientes del overview embed."""
    dist = client.get("/api/segmentos/distribucion").json()
    total = sum(r["n_clientes"] for r in dist)
    assert total > 0


# ─────────────────────────────────────────────────────────────────────────────
# /api/bundles
# ─────────────────────────────────────────────────────────────────────────────

def test_bundles_default_devuelve_reglas(client) -> None:
    r = client.get("/api/bundles")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    primero = data[0]
    for col in ["antecedents", "consequents", "confidence", "lift",
                "support_count", "revenue_total", "segmento"]:
        assert col in primero


def test_bundles_filtro_por_segmento(client) -> None:
    r = client.get("/api/bundles?segmento=MVPs&limit=5")
    assert r.status_code == 200
    data = r.json()
    assert all(row["segmento"] == "MVPs" for row in data)


def test_bundles_modo_completa_sin_revenue(client) -> None:
    """En modo completa, revenue_total y ticket_medio deben venir como null."""
    r = client.get("/api/bundles?modo=completa&limit=3")
    assert r.status_code == 200
    rows = r.json()
    assert rows, "modo completa debería devolver reglas"
    assert all(row["revenue_total"] is None for row in rows)


def test_bundles_modo_invalido_es_422(client) -> None:
    r = client.get("/api/bundles?modo=otrocosa")
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# /api/estacionalidad
# ─────────────────────────────────────────────────────────────────────────────

def test_estacionalidad_sin_params_usa_todos(client) -> None:
    r = client.get("/api/estacionalidad")
    assert r.status_code == 200
    data = r.json()
    assert set(data["seleccion"]) == {"MVPs", "Alto Valor", "Ocasionales",
                                      "En Riesgo", "Hibernando"}
    assert data["hora_dia"] and data["mensual"] and data["tipica"]


def test_estacionalidad_filtro_segmentos(client) -> None:
    r = client.get("/api/estacionalidad?segmentos=MVPs,Alto Valor")
    assert r.status_code == 200
    data = r.json()
    assert data["seleccion"] == ["MVPs", "Alto Valor"]
    assert all(row["segmento"] in ("MVPs", "Alto Valor") for row in data["hora_dia"])


def test_estacionalidad_pct_suma_uno_por_segmento(client) -> None:
    """La normalización a % del segmento debe sumar 1 (decisión del SPEC §6.3)."""
    data = client.get("/api/estacionalidad?segmentos=MVPs").json()
    suma = sum(row["pct"] for row in data["hora_dia"])
    assert abs(suma - 1.0) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# /api/comparador
# ─────────────────────────────────────────────────────────────────────────────

def test_comparador_devuelve_payload_completo(client) -> None:
    r = client.get("/api/comparador?seg_a=MVPs&seg_b=Hibernando")
    assert r.status_code == 200
    d = r.json()
    for key in ["seg_a", "seg_b", "metricas_a", "metricas_b",
                "bundles_a", "bundles_b", "monetary_a", "monetary_b", "ranges"]:
        assert key in d
    assert d["metricas_a"]["n_clientes"] > 0
    assert d["metricas_b"]["n_clientes"] > 0


def test_comparador_segmento_inexistente_devuelve_metricas_none(client) -> None:
    r = client.get("/api/comparador?seg_a=NoExiste&seg_b=MVPs")
    assert r.status_code == 200
    assert r.json()["metricas_a"] is None
    assert r.json()["metricas_b"] is not None


def test_comparador_sin_params_es_422(client) -> None:
    r = client.get("/api/comparador")
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# /api/heatmap-bundles
# ─────────────────────────────────────────────────────────────────────────────

def test_heatmap_bundles_mvps(client) -> None:
    r = client.get("/api/heatmap-bundles?segmento=MVPs")
    assert r.status_code == 200
    d = r.json()
    assert d["segmento"] == "MVPs"
    assert isinstance(d["serie"], list)
    assert isinstance(d["mes_pico"], list)


def test_heatmap_bundles_top_n_fuera_de_rango(client) -> None:
    r = client.get("/api/heatmap-bundles?segmento=MVPs&top_n=999")
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# /api/cliente/buscar
# ─────────────────────────────────────────────────────────────────────────────

def test_buscar_cliente_devuelve_matches(client) -> None:
    r = client.get("/api/cliente/buscar?q=A&limit=5")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    assert all("cliente_id" in row for row in data)


def test_buscar_cliente_sin_query_es_422(client) -> None:
    r = client.get("/api/cliente/buscar")
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# /api/cliente/{cliente_id}
# ─────────────────────────────────────────────────────────────────────────────

def test_cliente_drilldown_happy_path(client, cliente_real: str) -> None:
    r = client.get(f"/api/cliente/{cliente_real}")
    assert r.status_code == 200
    d = r.json()
    assert d["perfil"]["cliente_id"] == cliente_real
    assert isinstance(d["pedidos"], list)
    assert isinstance(d["posicion"], list)
    # Debe haber exactamente un punto marcado como objetivo
    objetivos = [p for p in d["posicion"] if p["es_objetivo"]]
    assert len(objetivos) == 1
    assert objetivos[0]["cliente_id"] == cliente_real


def test_cliente_drilldown_inexistente_devuelve_404(client) -> None:
    r = client.get("/api/cliente/CLIENTE_QUE_NO_EXISTE_XYZ_123")
    assert r.status_code == 404
    assert "no encontrado" in r.json()["detail"].lower()


def test_cliente_pedidos_limitados_a_50(client, cliente_real: str) -> None:
    """El endpoint cap a 50 pedidos por cliente (SPEC §6.4)."""
    d = client.get(f"/api/cliente/{cliente_real}").json()
    assert len(d["pedidos"]) <= 50
