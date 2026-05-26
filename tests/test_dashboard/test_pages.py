"""Smoke tests de las páginas HTML del dashboard.

Para cada vista verificamos:
- status 200
- content-type es HTML
- el HTML contiene un marcador esperado (id de un componente clave)
"""
from __future__ import annotations

import pytest


def test_root_redirige_a_overview(client) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/dashboard/overview"


@pytest.mark.parametrize(
    "slug,marker",
    [
        ("overview",        "Overview de segmentos"),
        ("bundles",         "Bundles accionables"),
        ("estacionalidad",  "Estacionalidad por segmento"),
        ("comparador",      "Comparador entre segmentos"),
        ("heatmap-bundles", "Heatmap de bundles"),
        ("alertas",         "Clientes valiosos en riesgo"),
        ("cliente",         "Drill-down por cliente"),
    ],
)
def test_vista_renderiza(client, slug: str, marker: str) -> None:
    r = client.get(f"/dashboard/{slug}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert marker in r.text


def test_overview_contiene_payload_embebido(client) -> None:
    r = client.get("/dashboard/overview")
    assert 'id="initial-data"' in r.text
    assert "donut-distribucion" in r.text
    assert "SEGMENT_COLORS" in r.text


def test_cliente_autocarga_desde_query_param(client, cliente_real: str) -> None:
    """La vista cliente acepta ?id= y precarga ese cliente_id en el initial-data."""
    r = client.get(f"/dashboard/cliente?id={cliente_real}")
    assert r.status_code == 200
    assert cliente_real in r.text


def test_alertas_linkea_a_perfil(client) -> None:
    """Cada fila de alertas debe linkear a /dashboard/cliente?id=..."""
    r = client.get("/dashboard/alertas")
    assert r.status_code == 200
    assert "/dashboard/cliente?id=" in r.text
