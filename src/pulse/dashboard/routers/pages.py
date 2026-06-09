"""Endpoints HTML del dashboard. Cada uno renderiza un Jinja2 template con un
`initial_data` payload embebido para evitar un fetch extra en la primera pintura.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pulse.dashboard import queries as q
from pulse.dashboard.db import SEGMENT_COLORS, SEGMENT_ORDER

log = logging.getLogger("pulse.dashboard.pages")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter()


def _base_context(vista_activa: str) -> dict:
    """Contexto común a todas las vistas: nav, paleta de segmentos."""
    return {
        "vista_activa": vista_activa,
        "segment_colors": SEGMENT_COLORS,
        "segment_order": SEGMENT_ORDER,
    }


@router.get("/overview", response_class=HTMLResponse)
async def overview(request: Request) -> HTMLResponse:
    """Overview de segmentos: KPIs, donut, bar, tabla resumen."""
    initial_data = {
        "kpis": q.kpis_globales(),
        "distribucion": q.distribucion_clientes(),
        "revenue": q.revenue_por_segmento(),
        "resumen": q.resumen_por_segmento(),
    }
    ctx = _base_context("overview")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "overview.html", ctx)


@router.get("/bundles", response_class=HTMLResponse)
async def bundles(request: Request) -> HTMLResponse:
    """Bundles accionables: bar chart top + tabla, con filtro segmento + modo."""
    initial_data = {
        "reglas": q.bundles_top_por_segmento(segmento=None, modo="accionables"),
    }
    ctx = _base_context("bundles")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "bundles.html", ctx)


@router.get("/estacionalidad", response_class=HTMLResponse)
async def estacionalidad(request: Request) -> HTMLResponse:
    """Heatmap hora×día, line chart mensual y bar chart estacionalidad típica."""
    todos = SEGMENT_ORDER
    initial_data = {
        "hora_dia": q.temporalidad_hora_dia(todos),
        "mensual": q.temporalidad_mensual(todos),
        "tipica": q.estacionalidad_tipica(todos),
        "seleccion_inicial": todos,
        # Modo "Último mes" (segment-independiente): se pre-carga oculto y el
        # toggle del front lo muestra sin un fetch extra.
        "ultimo_mes": {
            "actual":   q.temp_diario_ultimo_mes(),
            "anterior": q.temp_diario_mes_anterior_mismo_rango(),
            "kpis":     q.kpis_variacion_mensual(),
        },
    }
    ctx = _base_context("estacionalidad")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "estacionalidad.html", ctx)


def _comparador_payload(seg_a: str, seg_b: str) -> dict:
    """Construye el payload completo del comparador para dos segmentos."""
    return {
        "seg_a": seg_a,
        "seg_b": seg_b,
        "metricas_a": q.metricas_segmento(seg_a),
        "metricas_b": q.metricas_segmento(seg_b),
        "bundles_a": q.top_bundles_segmento(seg_a, limit=3),
        "bundles_b": q.top_bundles_segmento(seg_b, limit=3),
        "monetary_a": q.distribucion_monetary(seg_a),
        "monetary_b": q.distribucion_monetary(seg_b),
        "ranges": q.ranges_globales_por_segmento(),
    }


@router.get("/comparador", response_class=HTMLResponse)
async def comparador(request: Request) -> HTMLResponse:
    """Comparador entre dos segmentos: tabla, radar, box plot."""
    initial_data = _comparador_payload("MVPs", "Hibernando")
    ctx = _base_context("comparador")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "comparador.html", ctx)


def _heatmap_bundles_payload(segmento: str, top_n: int = 10) -> dict:
    return {
        "segmento": segmento,
        "serie": q.bundles_temporalidad(segmento, top_n=top_n),
        "mes_pico": q.mes_pico_por_bundle(segmento),
    }


@router.get("/heatmap-bundles", response_class=HTMLResponse)
async def heatmap_bundles(request: Request) -> HTMLResponse:
    """Heatmap de los top bundles de un segmento contra los meses."""
    initial_data = _heatmap_bundles_payload("MVPs")
    ctx = _base_context("heatmap-bundles")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "heatmap_bundles.html", ctx)


@router.get("/alertas", response_class=HTMLResponse)
async def alertas(request: Request) -> HTMLResponse:
    """Clientes valiosos en riesgo: dos tabs (urgentes y reactivación masiva)."""
    initial_data = {
        "urgentes": {
            "kpis": q.kpis_urgentes(),
            "clientes": q.clientes_urgentes(),
        },
        "reactivacion": {
            "kpis": q.kpis_reactivacion(),
            "clientes": q.clientes_reactivacion(),
        },
    }
    ctx = _base_context("alertas")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "alertas.html", ctx)


@router.get("/movimientos", response_class=HTMLResponse)
async def movimientos(request: Request) -> HTMLResponse:
    """Clientes en transición: frontera espacial + cambios de segmento mes a mes."""
    frontera = q.clientes_en_frontera(threshold=0.7)
    cambios = q.clientes_cambio_segmento(meses_atras=1)
    initial_data = {
        "kpis":     q.kpis_movimientos(frontera, cambios),
        "frontera": frontera,
        "cambios":  cambios,
    }
    ctx = _base_context("movimientos")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "movimientos.html", ctx)


@router.get("/cliente", response_class=HTMLResponse)
async def cliente(request: Request) -> HTMLResponse:
    """Drill-down por cliente. Acepta ?id=… para autocargar desde alertas."""
    ctx = _base_context("cliente")
    cid = request.query_params.get("id")
    ctx["initial_data"] = {"cliente_id": cid}
    return templates.TemplateResponse(request, "cliente.html", ctx)
