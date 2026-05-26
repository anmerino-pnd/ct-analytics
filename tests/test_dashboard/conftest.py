"""Fixtures comunes a los tests del dashboard.

Usamos TestClient como context manager para que el `lifespan` se ejecute
una sola vez por sesión (calienta DuckDB y registra vistas). Scope=session
para no pagar el setup en cada test.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from pulse.dashboard.app import app


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def cliente_real(client: TestClient) -> str:
    """Devuelve un cliente_id que existe en la base, para tests de drill-down."""
    r = client.get("/api/cliente/buscar?q=A&limit=1")
    assert r.status_code == 200, "buscar_cliente no responde"
    matches = r.json()
    assert matches, "no hay clientes en la base — verifica el parquet"
    return matches[0]["cliente_id"]
