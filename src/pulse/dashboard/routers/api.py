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
) -> list[dict]:
    """Reglas para el scatter Market Basket Opportunity Map.
    Filtra por confidence > 0.3 y lift > 1.5 (igual que v3).
    """
    seg = segmento if segmento and segmento != "Todos" else None
    return q.bundles_scatter_map(segmento=seg, modo=modo)


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


@router.get("/estacionalidad/ultimo-mes")
async def estacionalidad_ultimo_mes() -> dict:
    """Vista 'Último mes': diario del mes en curso vs mismo rango del mes anterior."""
    return {
        "actual":   q.temp_diario_ultimo_mes(),
        "anterior": q.temp_diario_mes_anterior_mismo_rango(),
        "kpis":     q.kpis_variacion_mensual(),
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
    """Payload completo del cliente: perfil, pedidos, posición, productos, bundles, oportunidades."""
    perfil = q.cliente_perfil(cliente_id)
    if perfil is None:
        raise HTTPException(
            status_code=404,
            detail=f"Cliente '{cliente_id}' no encontrado",
        )
    return {
        "perfil": perfil,
        "pedidos": q.cliente_pedidos(cliente_id),
        "posicion": q.cliente_posicion_segmento(cliente_id),
        "productos_top": q.cliente_productos_top(cliente_id, limit=10),
        "bundles_propios": q.cliente_bundles_propios(cliente_id, limit=10),
        "oportunidades": q.cliente_oportunidades(cliente_id, limit=10),
    }


# ─────────────────────────────────────────────────────────────────────────────
# /api/alertas/* — tabs Urgentes y Reactivación masiva
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/alertas/urgentes")
async def alertas_urgentes() -> dict:
    """MVPs / Alto Valor en riesgo individual (acción de cuenta key)."""
    return {
        "kpis": q.kpis_urgentes(),
        "clientes": q.clientes_urgentes(),
    }


@router.get("/alertas/reactivacion")
async def alertas_reactivacion() -> dict:
    """Segmento En Riesgo completo (campaña masiva de reactivación)."""
    return {
        "kpis": q.kpis_reactivacion(),
        "clientes": q.clientes_reactivacion(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# /api/movimientos — clientes en transición entre segmentos
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/movimientos")
async def movimientos() -> dict:
    """Clientes en frontera (espacial) y cambios de segmento (temporal)."""
    frontera = q.clientes_en_frontera(threshold=0.7)
    cambios = q.clientes_cambio_segmento(meses_atras=1)
    return {
        "kpis":     q.kpis_movimientos(frontera, cambios),
        "frontera": frontera,
        "cambios":  cambios,
    }
