"""Fixtures comunes a los tests del dashboard.

Usamos TestClient como context manager para que el `lifespan` se ejecute
una sola vez por sesión (calienta DuckDB y registra vistas). Scope=session
para no pagar el setup en cada test.

────────────────────────────────────────────────────────────────────────────
DECISIÓN TEMPORAL (CI) — skip cuando faltan los parquets de producción
────────────────────────────────────────────────────────────────────────────
Estos tests son de integración: pegan a DuckDB sobre los parquets reales de
`datos/processed/` (gitignored). En GitHub Actions esos archivos no existen y
regenerarlos requeriría MongoDB, así que el módulo completo se SKIPEA cuando
falta el parquet canónico (ver `pytest_collection_modifyitems` abajo). En local,
con los parquets presentes, corren los 136 tests normalmente.

Esto es un puente, NO la solución final. En una iteración futura migraremos los
tests críticos a fixtures sintéticos (parquets pequeños bajo `tests/fixtures/`)
para que corran también en CI. Orden de migración sugerido, de más a menos
urgente (validan invariantes que ya rompieron prod o que son fáciles de romper):

  1. test_queries.py::test_cliente_productos_top_excluye_cargo
       — filtrado de CARGO100 fuera del drill-down de productos.
  2. test_queries.py::test_ratio_no_es_infinito
       — ratio defensivo contra cadencia=0 (GREATEST evita None/infinito).
  3. test_api.py::test_estacionalidad_pct_suma_uno_por_segmento
       — cross-check temporalidad ↔ RFM: la distribución temporal por segmento
         debe sumar 1.
  4. test_queries.py::test_clientes_en_frontera_threshold
       — respeto del threshold de razón de distancias y exclusión de single-buyers.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pulse.config.paths import PROCESSED
from pulse.dashboard.app import app

# Si falta este parquet canónico asumimos que TODOS los parquets faltan
# (entorno sin datos de producción, p. ej. CI) y skipeamos el módulo entero.
_REQUIRED_PARQUET = PROCESSED / "clientes_segmentados.parquet"
_HERE = Path(__file__).parent


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip por sesión (un solo check) de todos los tests del dashboard si no
    hay parquets de producción. El skip es visible y nombrado en el reporte."""
    if _REQUIRED_PARQUET.exists():
        return

    skip_marker = pytest.mark.skip(reason="requires production parquets")
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(skip_marker)


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
