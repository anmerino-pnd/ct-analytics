"""Queries SQL parametrizadas para el dashboard.

Cada función representa una pregunta de negocio del SPEC y devuelve `list[dict]`
(o `dict | None` para perfiles individuales). Los routers consumen estas
funciones directamente — no escriben SQL ellos mismos.

Reglas:
- Toda parametrización va con `?` y lista de params, NUNCA f-strings con valores.
- Los alias de columnas son explícitos (`AS …`) para que el JSON tenga nombres
  estables sin depender del orden de DuckDB.
- Las columnas con `ñ` (`año_mes`) van entre comillas dobles en SQL.
"""
from __future__ import annotations

from typing import Literal

from pulse.dashboard.db import fetch_dicts


# ─────────────────────────────────────────────────────────────────────────────
# 6.1 Overview de segmentos
# ─────────────────────────────────────────────────────────────────────────────

def kpis_globales() -> dict:
    """KPIs de toda la base: n clientes, revenue total, ticket promedio, % single-buyers."""
    rows = fetch_dicts(
        """
        SELECT
          COUNT(*)                                  AS n_clientes,
          SUM(monetary)                             AS revenue_total,
          SUM(monetary) / NULLIF(SUM(frequency), 0) AS ticket_promedio,
          AVG(CAST(es_single_buyer AS DOUBLE))      AS pct_single_buyers
        FROM segmentos
        """
    )
    return rows[0]


def distribucion_clientes() -> list[dict]:
    """Conteo de clientes por segmento (para donut chart)."""
    return fetch_dicts(
        """
        SELECT segmento_cluster AS segmento,
               COUNT(*)         AS n_clientes
        FROM segmentos
        GROUP BY segmento_cluster
        ORDER BY n_clientes DESC
        """
    )


def revenue_por_segmento() -> list[dict]:
    """Revenue total (sumatoria de monetary) por segmento."""
    return fetch_dicts(
        """
        SELECT segmento_cluster AS segmento,
               SUM(monetary)    AS revenue
        FROM segmentos
        GROUP BY segmento_cluster
        ORDER BY revenue DESC
        """
    )


def resumen_por_segmento() -> list[dict]:
    """Tabla resumen: una fila por segmento con métricas medianas."""
    return fetch_dicts(
        """
        WITH total AS (SELECT COUNT(*) AS n_total FROM segmentos)
        SELECT
          segmento_cluster                                              AS segmento,
          COUNT(*)                                                      AS n_clientes,
          COUNT(*) * 1.0 / (SELECT n_total FROM total)                  AS pct,
          MEDIAN(recency)                                               AS recency_med,
          MEDIAN(frequency)                                             AS frequency_med,
          MEDIAN(monetary)                                              AS monetary_med,
          MEDIAN(dias_entre_compras)                                    AS cadencia_med
        FROM segmentos
        GROUP BY segmento_cluster
        ORDER BY monetary_med DESC
        """
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6.2 Bundles accionables
# ─────────────────────────────────────────────────────────────────────────────

def bundles_top_por_segmento(
    segmento: str | None,
    modo: Literal["accionables", "completa"] = "accionables",
    limit: int = 15,
) -> list[dict]:
    """Top N reglas de market basket por segmento.

    En modo `accionables` ordena por `revenue_total` (campo solo presente en
    `mba_reglas_accionables`). En modo `completa` consume `mba_por_segmento`
    y ordena por `support_count` (las columnas de revenue/ticket no existen
    en ese parquet).
    """
    if modo == "accionables":
        base = """
            SELECT antecedents, consequents, confidence, lift,
                   support_count, n_pedidos,
                   ticket_medio, ticket_mediano, revenue_total,
                   segmento
            FROM mba_accionables
        """
        order_by = "ORDER BY revenue_total DESC"
    else:
        base = """
            SELECT antecedents, consequents, confidence, lift,
                   support_count,
                   CAST(NULL AS DOUBLE) AS n_pedidos,
                   CAST(NULL AS DOUBLE) AS ticket_medio,
                   CAST(NULL AS DOUBLE) AS ticket_mediano,
                   CAST(NULL AS DOUBLE) AS revenue_total,
                   segmento
            FROM mba_por_segmento
        """
        order_by = "ORDER BY support_count DESC"

    if segmento and segmento != "Todos":
        sql = f"{base} WHERE segmento = ? {order_by} LIMIT ?"
        params = [segmento, limit]
    else:
        sql = f"{base} {order_by} LIMIT ?"
        params = [limit]
    return fetch_dicts(sql, params)


# ─────────────────────────────────────────────────────────────────────────────
# 6.3 Estacionalidad
# ─────────────────────────────────────────────────────────────────────────────

def temporalidad_hora_dia(segmentos: list[str]) -> list[dict]:
    """Pedidos por (segmento, día, hora), normalizados a % del total del segmento.

    Decisión del SPEC: el heatmap muestra el *patrón* de actividad, no el
    volumen. Dos segmentos con tamaños distintos se ven comparables.
    """
    return fetch_dicts(
        """
        WITH totales AS (
          SELECT segmento_cluster, SUM(pedidos) AS total
          FROM temp_hora_dia
          GROUP BY segmento_cluster
        )
        SELECT
          t.segmento_cluster                       AS segmento,
          t.dia_semana,
          t.dia_nombre,
          t.hora,
          t.pedidos,
          t.pedidos * 1.0 / NULLIF(tot.total, 0)   AS pct
        FROM temp_hora_dia t
        JOIN totales tot USING (segmento_cluster)
        WHERE list_contains(?, t.segmento_cluster)
        ORDER BY t.segmento_cluster, t.dia_semana, t.hora
        """,
        [segmentos],
    )


def temporalidad_mensual(segmentos: list[str]) -> list[dict]:
    """Pedidos y revenue por (segmento, año_mes). Serie temporal completa."""
    return fetch_dicts(
        """
        SELECT
          segmento_cluster AS segmento,
          "año_mes"        AS ano_mes,
          pedidos,
          revenue
        FROM temp_mes
        WHERE list_contains(?, segmento_cluster)
        ORDER BY "año_mes", segmento_cluster
        """,
        [segmentos],
    )


def estacionalidad_tipica(segmentos: list[str]) -> list[dict]:
    """Promedio de pedidos por mes calendario (1-12), promediando entre años."""
    return fetch_dicts(
        """
        SELECT
          segmento_cluster                                       AS segmento,
          CAST(substr("año_mes", 6, 2) AS INTEGER)               AS mes,
          AVG(pedidos)                                           AS pedidos_promedio
        FROM temp_mes
        WHERE list_contains(?, segmento_cluster)
        GROUP BY segmento_cluster, mes
        ORDER BY segmento_cluster, mes
        """,
        [segmentos],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6.4 Drill-down por cliente
# ─────────────────────────────────────────────────────────────────────────────

def buscar_cliente(query: str, limit: int = 20) -> list[dict]:
    """Autocomplete: cliente_ids que contienen el query (case-insensitive)."""
    patron = f"%{query}%"
    return fetch_dicts(
        """
        SELECT DISTINCT cliente_id
        FROM segmentos
        WHERE cliente_id ILIKE ?
        ORDER BY cliente_id
        LIMIT ?
        """,
        [patron, limit],
    )


def cliente_perfil(cliente_id: str) -> dict | None:
    """Perfil completo del cliente o None si no existe."""
    rows = fetch_dicts(
        """
        SELECT cliente_id,
               recency,
               frequency,
               monetary,
               dias_entre_compras,
               es_single_buyer,
               cluster_id AS cluster,
               segmento_cluster AS segmento
        FROM segmentos
        WHERE cliente_id = ?
        """,
        [cliente_id],
    )
    return rows[0] if rows else None


def cliente_pedidos(cliente_id: str, limit: int = 50) -> list[dict]:
    """Últimos N pedidos del cliente, más recientes primero."""
    return fetch_dicts(
        """
        SELECT order_id,
               strftime(fecha, '%Y-%m-%d %H:%M:%S') AS fecha,
               pago_total,
               num_productos
        FROM orders
        WHERE cliente_id = ?
        ORDER BY fecha DESC
        LIMIT ?
        """,
        [cliente_id, limit],
    )


def cliente_posicion_segmento(cliente_id: str) -> list[dict]:
    """Todos los clientes del mismo segmento (para scatter), con flag del target."""
    return fetch_dicts(
        """
        WITH target AS (
          SELECT segmento_cluster FROM segmentos WHERE cliente_id = ?
        )
        SELECT cliente_id,
               recency,
               monetary,
               (cliente_id = ?) AS es_objetivo
        FROM segmentos
        WHERE segmento_cluster = (SELECT segmento_cluster FROM target)
        """,
        [cliente_id, cliente_id],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6.5 Alertas: clientes valiosos en riesgo
# ─────────────────────────────────────────────────────────────────────────────

def clientes_en_riesgo() -> list[dict]:
    """MVPs / Alto Valor no single-buyers cuyo recency excede 1.5× su cadencia mediana."""
    return fetch_dicts(
        """
        SELECT
          cliente_id,
          segmento_cluster                                       AS segmento,
          recency,
          dias_entre_compras                                     AS cadencia,
          recency * 1.0 / NULLIF(dias_entre_compras, 0)          AS ratio,
          monetary,
          frequency
        FROM segmentos
        WHERE segmento_cluster IN ('MVPs', 'Alto Valor')
          AND es_single_buyer = 0
          AND recency > 1.5 * dias_entre_compras
        ORDER BY monetary DESC
        """
    )


def kpis_alertas() -> dict:
    """Conteos y revenue acumulado de los clientes en riesgo (para las KPI cards)."""
    rows = fetch_dicts(
        """
        SELECT
          COUNT(*)                                                                    AS n_total,
          SUM(CASE WHEN segmento_cluster = 'MVPs' THEN 1 ELSE 0 END)                  AS n_mvps,
          SUM(CASE WHEN segmento_cluster = 'Alto Valor' THEN 1 ELSE 0 END)            AS n_alto,
          SUM(monetary)                                                               AS revenue_en_riesgo
        FROM segmentos
        WHERE segmento_cluster IN ('MVPs', 'Alto Valor')
          AND es_single_buyer = 0
          AND recency > 1.5 * dias_entre_compras
        """
    )
    return rows[0]


# ─────────────────────────────────────────────────────────────────────────────
# 6.6 Comparador entre segmentos
# ─────────────────────────────────────────────────────────────────────────────

def metricas_segmento(segmento: str) -> dict | None:
    """Métricas agregadas (mediana, media, total, pct) de un segmento.

    Devuelve None si el segmento no existe.
    """
    rows = fetch_dicts(
        """
        WITH total AS (SELECT COUNT(*) AS n_total FROM segmentos)
        SELECT
          ?                                                              AS segmento,
          COUNT(*)                                                       AS n_clientes,
          COUNT(*) * 1.0 / NULLIF((SELECT n_total FROM total), 0)        AS pct_total,
          MEDIAN(recency)                                                AS recency_med,
          AVG(recency)                                                   AS recency_avg,
          MEDIAN(frequency)                                              AS frequency_med,
          AVG(frequency)                                                 AS frequency_avg,
          MEDIAN(monetary)                                               AS monetary_med,
          AVG(monetary)                                                  AS monetary_avg,
          SUM(monetary)                                                  AS monetary_total,
          MEDIAN(dias_entre_compras)                                     AS cadencia_med,
          AVG(CAST(es_single_buyer AS DOUBLE))                           AS pct_single_buyers
        FROM segmentos
        WHERE segmento_cluster = ?
        """,
        [segmento, segmento],
    )
    if not rows or rows[0]["n_clientes"] == 0:
        return None
    return rows[0]


def top_bundles_segmento(segmento: str, limit: int = 3) -> list[dict]:
    """Top N bundles accionables del segmento (atajo para el comparador)."""
    return bundles_top_por_segmento(segmento, modo="accionables", limit=limit)


def distribucion_monetary(segmento: str) -> list[float]:
    """Lista plana de monetary de los clientes del segmento (para violin/box)."""
    rows = fetch_dicts(
        """
        SELECT monetary
        FROM segmentos
        WHERE segmento_cluster = ?
        """,
        [segmento],
    )
    return [r["monetary"] for r in rows]


def ranges_globales() -> dict:
    """Min/max de cada métrica RFM+cadencia sobre TODA la base.

    Usado por el radar del comparador para normalizar al rango 0-1 contra todos
    los segmentos (no solo los dos comparados — decisión del SPEC §6.6).
    """
    rows = fetch_dicts(
        """
        SELECT
          MIN(recency) AS recency_min, MAX(recency) AS recency_max,
          MIN(frequency) AS frequency_min, MAX(frequency) AS frequency_max,
          MIN(monetary) AS monetary_min, MAX(monetary) AS monetary_max,
          MIN(dias_entre_compras) AS cadencia_min, MAX(dias_entre_compras) AS cadencia_max
        FROM segmentos
        """
    )
    return rows[0]


# ─────────────────────────────────────────────────────────────────────────────
# 6.7 Heatmap bundles × mes × segmento
# ─────────────────────────────────────────────────────────────────────────────

def bundles_temporalidad(segmento: str, top_n: int = 10) -> list[dict]:
    """Serie mensual de los top N bundles de un segmento (por revenue total)."""
    return fetch_dicts(
        """
        WITH top_reglas AS (
          SELECT regla
          FROM temp_bundles
          WHERE segmento_regla = ?
          GROUP BY regla
          ORDER BY SUM(revenue) DESC
          LIMIT ?
        )
        SELECT t.regla,
               t."año_mes" AS ano_mes,
               t.pedidos,
               t.revenue
        FROM temp_bundles t
        JOIN top_reglas tr USING (regla)
        WHERE t.segmento_regla = ?
        ORDER BY t.regla, t."año_mes"
        """,
        [segmento, top_n, segmento],
    )


def mes_pico_por_bundle(segmento: str) -> list[dict]:
    """Para cada bundle del segmento, el año_mes con mayor concentración de pedidos."""
    return fetch_dicts(
        """
        WITH ranked AS (
          SELECT regla,
                 "año_mes",
                 pedidos,
                 ROW_NUMBER() OVER (PARTITION BY regla ORDER BY pedidos DESC) AS rk,
                 SUM(pedidos) OVER (PARTITION BY regla)                        AS total_pedidos
          FROM temp_bundles
          WHERE segmento_regla = ?
        )
        SELECT regla,
               "año_mes"                                  AS mes_pico,
               pedidos,
               pedidos * 1.0 / NULLIF(total_pedidos, 0)   AS pct_concentracion
        FROM ranked
        WHERE rk = 1
        ORDER BY pedidos DESC
        """,
        [segmento],
    )
