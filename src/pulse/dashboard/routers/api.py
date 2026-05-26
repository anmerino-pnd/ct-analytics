"""Endpoints JSON consumidos por el JS del cliente para filtros / drill-downs.

Cada endpoint llama a una función pura de `queries.py` y devuelve su resultado
directamente. Sin lógica de presentación aquí — el frontend transforma a Plotly.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from pulse.dashboard import queries as q

log = logging.getLogger("pulse.dashboard.api")

router = APIRouter()


@router.get("/segmentos/distribucion")
async def distribucion_segmentos() -> list[dict]:
    """Cuenta de clientes por segmento. Sirve como ping del patrón DuckDB."""
    return q.distribucion_clientes()


@router.get("/bundles")
async def bundles(
    segmento: str | None = Query(default=None),
    modo: Literal["accionables", "completa"] = Query(default="accionables"),
    limit: int = Query(default=15, ge=1, le=100),
) -> list[dict]:
    """Top reglas de market basket. `segmento` vacío o 'Todos' = todos los segmentos."""
    seg = segmento if segmento and segmento != "Todos" else None
    return q.bundles_top_por_segmento(segmento=seg, modo=modo, limit=limit)


def _parse_segmentos(segmentos: str | None) -> list[str]:
    """Parsea el querystring `?segmentos=MVPs,Alto Valor,...` a lista de strings."""
    if not segmentos:
        return []
    return [s.strip() for s in segmentos.split(",") if s.strip()]


@router.get("/estacionalidad")
async def estacionalidad(
    segmentos: str | None = Query(default=None),
) -> dict:
    """Datos de estacionalidad: heatmap hora×día, serie mensual y mes calendario."""
    seg_list = _parse_segmentos(segmentos)
    if not seg_list:
        from pulse.dashboard.db import SEGMENT_ORDER
        seg_list = SEGMENT_ORDER
    return {
        "hora_dia": q.temporalidad_hora_dia(seg_list),
        "mensual": q.temporalidad_mensual(seg_list),
        "tipica": q.estacionalidad_tipica(seg_list),
        "seleccion": seg_list,
    }


@router.get("/comparador")
async def comparador(
    seg_a: str = Query(...),
    seg_b: str = Query(...),
) -> dict:
    """Payload del comparador: métricas, top bundles, monetary y ranges globales."""
    from pulse.dashboard.routers.pages import _comparador_payload
    return _comparador_payload(seg_a, seg_b)


@router.get("/heatmap-bundles")
async def heatmap_bundles(
    segmento: str = Query(...),
    top_n: int = Query(default=10, ge=1, le=30),
) -> dict:
    """Serie mensual y mes pico de los top N bundles de un segmento."""
    from pulse.dashboard.routers.pages import _heatmap_bundles_payload
    return _heatmap_bundles_payload(segmento, top_n=top_n)


@router.get("/cliente/buscar")
async def buscar_cliente(
    q_text: str = Query(..., alias="q", min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[dict]:
    """Autocomplete: lista de cliente_ids que contienen el query (case-insensitive)."""
    return q.buscar_cliente(q_text, limit=limit)


@router.get("/cliente/{cliente_id}")
async def cliente_drilldown(cliente_id: str) -> dict:
    """Payload completo del cliente: perfil, pedidos, posición en su segmento."""
    perfil = q.cliente_perfil(cliente_id)
    if perfil is None:
        raise HTTPException(
            status_code=404,
            detail=f"Cliente '{cliente_id}' no encontrado",
        )
    return {
        "perfil": perfil,
        "pedidos": q.cliente_pedidos(cliente_id, limit=50),
        "posicion": q.cliente_posicion_segmento(cliente_id),
    }
