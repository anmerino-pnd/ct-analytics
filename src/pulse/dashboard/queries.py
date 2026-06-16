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
        sql = f"{base} WHERE segmento = ? {order_by}"
        params = [segmento]
    else:
        sql = f"{base} {order_by}"
        params = None
    return fetch_dicts(sql, params)


def bundles_scatter_map(
    segmento: str | None,
    modo: Literal["accionables", "completa"] = "accionables",
    min_confidence: float = 0.30,
    min_lift: float = 1.5,
) -> list[dict]:
    """Reglas para el Market Basket Opportunity Map.

    A diferencia de `bundles_top_por_segmento`, NO limita por count — devuelve
    TODAS las reglas que pasan los umbrales mínimos. El scatter las distribuye
    en el plano confidence × lift.

    Los umbrales son los de v3 (confidence > 0.3, lift > 1.5). Ordenadas por
    lift desc, confidence desc — mismo orden que la tabla pedida.
    """
    if modo == "accionables":
        base = """
            SELECT antecedents, consequents, confidence, lift,
                   support_count, n_pedidos,
                   ticket_medio, ticket_mediano, revenue_total,
                   segmento
            FROM mba_accionables
        """
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

    filtros = ["confidence > ?", "lift > ?"]
    params: list = [min_confidence, min_lift]

    if segmento and segmento != "Todos":
        filtros.append("segmento = ?")
        params.append(segmento)

    where = " AND ".join(filtros)
    sql = f"""
        {base}
        WHERE {where}
        ORDER BY lift DESC, confidence DESC
    """
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


def temp_diario_ultimo_mes() -> list[dict]:
    """Datos diarios del mes en curso, por segmento (vista 'Último mes')."""
    return fetch_dicts(
        """
        SELECT CAST(fecha_dia AS VARCHAR) AS fecha_dia, segmento, pedidos, revenue
        FROM temp_diario
        WHERE date_trunc('month', fecha_dia) = date_trunc('month', current_date)
        ORDER BY fecha_dia, segmento
        """
    )


def temp_diario_mes_anterior_mismo_rango() -> list[dict]:
    """Datos diarios del mes anterior, limitados al mismo día relativo.

    Si hoy es 2026-06-09, devuelve datos del 2026-05-01 al 2026-05-09.
    """
    return fetch_dicts(
        """
        SELECT CAST(fecha_dia AS VARCHAR) AS fecha_dia, segmento, pedidos, revenue
        FROM temp_diario
        WHERE fecha_dia >= date_trunc('month', current_date - INTERVAL '1 month')
          AND fecha_dia <= (current_date - INTERVAL '1 month')
        ORDER BY fecha_dia, segmento
        """
    )


def kpis_variacion_mensual() -> dict:
    """KPIs de variación: pedidos del mes en curso vs mismo rango del mes anterior."""
    rows = fetch_dicts(
        """
        WITH actual AS (
            SELECT segmento, SUM(pedidos) AS pedidos_actual
            FROM temp_diario
            WHERE date_trunc('month', fecha_dia) = date_trunc('month', current_date)
            GROUP BY segmento
        ),
        anterior AS (
            SELECT segmento, SUM(pedidos) AS pedidos_anterior
            FROM temp_diario
            WHERE fecha_dia >= date_trunc('month', current_date - INTERVAL '1 month')
              AND fecha_dia <= (current_date - INTERVAL '1 month')
            GROUP BY segmento
        )
        SELECT
            COALESCE(a.segmento, b.segmento)                         AS segmento,
            COALESCE(a.pedidos_actual, 0)                            AS pedidos_actual,
            COALESCE(b.pedidos_anterior, 0)                          AS pedidos_anterior,
            CASE
                WHEN COALESCE(b.pedidos_anterior, 0) = 0 THEN NULL
                ELSE (COALESCE(a.pedidos_actual, 0) - b.pedidos_anterior)
                     * 100.0 / b.pedidos_anterior
            END                                                      AS variacion_pct
        FROM actual a
        FULL OUTER JOIN anterior b USING (segmento)
        ORDER BY segmento
        """
    )

    total_actual = sum(r["pedidos_actual"] for r in rows)
    total_anterior = sum(r["pedidos_anterior"] for r in rows)
    total_variacion = (
        ((total_actual - total_anterior) * 100.0 / total_anterior)
        if total_anterior > 0
        else None
    )

    return {
        "por_segmento": rows,
        "total_actual": total_actual,
        "total_anterior": total_anterior,
        "total_variacion_pct": total_variacion,
    }


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


def cliente_pedidos(cliente_id: str) -> list[dict]:
    """Historial COMPLETO de pedidos del cliente, en orden cronológico (ASC).

    Sin límite: alimenta la gráfica de historial completo. Por pedido devuelve
    `num_productos` (productos únicos) y `unidades_totales` (suma de cantidad de
    items, excluyendo CARGO100).
    """
    return fetch_dicts(
        """
        SELECT o.order_id,
               strftime(o.fecha, '%Y-%m-%d %H:%M:%S')                            AS fecha,
               o.pago_total,
               o.num_productos,
               COALESCE(SUM(i.cantidad) FILTER (WHERE i.clave != 'CARGO100'), 0) AS unidades_totales
        FROM orders o
        LEFT JOIN items i USING (order_id)
        WHERE o.cliente_id = ?
        GROUP BY o.order_id, o.fecha, o.pago_total, o.num_productos
        ORDER BY o.fecha
        """,
        [cliente_id],
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


def cliente_productos_top(cliente_id: str, limit: int = 10) -> list[dict]:
    """Top N familias compradas por un cliente, ordenadas por revenue total.

    Excluye CARGO100 (cargo financiero, no producto).
    Lee desde la vista 'items' que apunta a items_historicos.parquet.
    """
    return fetch_dicts(
        """
        SELECT
            familia,
            COUNT(DISTINCT order_id)                          AS n_pedidos,
            SUM(cantidad)                                     AS unidades_totales,
            SUM(subtotal_mxn)                                 AS revenue_total,
            strftime(MAX(fecha), '%Y-%m-%d')                  AS ultima_compra
        FROM items
        WHERE cliente_id = ?
          AND clave != 'CARGO100'
          AND familia IS NOT NULL
        GROUP BY familia
        ORDER BY revenue_total DESC
        LIMIT ?
        """,
        [cliente_id, limit],
    )


def cliente_bundles_propios(cliente_id: str, limit: int = 10) -> list[dict]:
    """Pares de familias que el cliente compra juntas en la misma orden.

    Cruza con mba_accionables del segmento para anexar lift y confidence
    cuando la regla también es válida a nivel de segmento.
    """
    # 1. Pares de familias en las mismas órdenes del cliente
    pares = fetch_dicts(
        """
        WITH items_cliente AS (
            SELECT DISTINCT order_id, familia
            FROM items
            WHERE cliente_id = ?
              AND clave != 'CARGO100'
              AND familia IS NOT NULL
        )
        SELECT
            a.familia                AS familia_a,
            b.familia                AS familia_b,
            COUNT(DISTINCT a.order_id) AS n_ordenes
        FROM items_cliente a
        JOIN items_cliente b USING (order_id)
        WHERE a.familia < b.familia
        GROUP BY a.familia, b.familia
        HAVING COUNT(DISTINCT a.order_id) >= 2
        ORDER BY n_ordenes DESC
        LIMIT ?
        """,
        [cliente_id, limit],
    )
    if not pares:
        return []

    # 2. Total de órdenes del cliente
    total_row = fetch_dicts(
        "SELECT COUNT(DISTINCT order_id) AS total FROM items WHERE cliente_id = ? AND clave != 'CARGO100'",
        [cliente_id],
    )
    total_ordenes = total_row[0]["total"] if total_row else 0

    # 3. Segmento del cliente
    seg_row = fetch_dicts(
        "SELECT segmento_cluster FROM segmentos WHERE cliente_id = ?",
        [cliente_id],
    )
    segmento = seg_row[0]["segmento_cluster"] if seg_row else None

    # 4. Reglas MBA accionables del segmento (mapa par → {confidence, lift})
    reglas_map = {}
    if segmento:
        reglas = fetch_dicts(
            "SELECT antecedents, consequents, confidence, lift FROM mba_accionables WHERE segmento = ?",
            [segmento],
        )
        for r in reglas:
            if "," not in r["consequents"]:  # solo bundles 1→1
                par_norm = tuple(sorted([r["antecedents"], r["consequents"]]))
                reglas_map[par_norm] = {"confidence": r["confidence"], "lift": r["lift"]}

    # 5. Anexar info al par
    for p in pares:
        par_norm = tuple(sorted([p["familia_a"], p["familia_b"]]))
        regla = reglas_map.get(par_norm)
        p["confidence_segmento"] = regla["confidence"] if regla else None
        p["lift_segmento"] = regla["lift"] if regla else None
        p["pct_aparicion"] = (p["n_ordenes"] / total_ordenes) if total_ordenes else 0.0

    return pares


def cliente_oportunidades(cliente_id: str, limit: int = 10) -> list[dict]:
    """Órdenes donde compró parte de un bundle propio pero no completo.

    Define 'bundle fuerte' como pares con co-ocurrencia >= 30% respecto a la
    familia menos frecuente del par. Devuelve las órdenes con la oportunidad
    (las que contienen exactamente una de las dos familias del bundle).

    Una sola query set-based: cruza cada bundle fuerte con las órdenes del
    cliente y marca presencia de cada familia; la oportunidad existe cuando solo
    una de las dos está presente (has_a + has_b = 1).
    """
    return fetch_dicts(
        """
        WITH items_cliente AS (
            SELECT DISTINCT order_id, familia
            FROM items
            WHERE cliente_id = ?
              AND clave != 'CARGO100'
              AND familia IS NOT NULL
        ),
        pares AS (
            SELECT
                a.familia                       AS familia_a,
                b.familia                       AS familia_b,
                COUNT(DISTINCT a.order_id)      AS n_juntas
            FROM items_cliente a
            JOIN items_cliente b USING (order_id)
            WHERE a.familia < b.familia
            GROUP BY a.familia, b.familia
        ),
        apariciones AS (
            SELECT familia, COUNT(DISTINCT order_id) AS n_total
            FROM items_cliente
            GROUP BY familia
        ),
        bundles_fuertes AS (
            SELECT
                p.familia_a,
                p.familia_b,
                p.n_juntas * 1.0 / LEAST(ap_a.n_total, ap_b.n_total) AS co_occurrence
            FROM pares p
            JOIN apariciones ap_a ON ap_a.familia = p.familia_a
            JOIN apariciones ap_b ON ap_b.familia = p.familia_b
            WHERE p.n_juntas >= 2
              AND p.n_juntas * 1.0 / LEAST(ap_a.n_total, ap_b.n_total) >= 0.30
        ),
        orden_bundle AS (
            SELECT
                bf.familia_a,
                bf.familia_b,
                bf.co_occurrence,
                ic.order_id,
                MAX(CASE WHEN ic.familia = bf.familia_a THEN 1 ELSE 0 END) AS has_a,
                MAX(CASE WHEN ic.familia = bf.familia_b THEN 1 ELSE 0 END) AS has_b
            FROM bundles_fuertes bf
            CROSS JOIN items_cliente ic
            GROUP BY bf.familia_a, bf.familia_b, bf.co_occurrence, ic.order_id
        )
        SELECT
            o.order_id,
            strftime(o.fecha, '%Y-%m-%d %H:%M:%S')                         AS fecha,
            o.pago_total,
            CASE WHEN ob.has_a = 1 THEN ob.familia_a ELSE ob.familia_b END AS compro,
            CASE WHEN ob.has_a = 1 THEN ob.familia_b ELSE ob.familia_a END AS le_falto,
            ob.co_occurrence
        FROM orden_bundle ob
        JOIN orders o ON o.order_id = ob.order_id AND o.cliente_id = ?
        WHERE ob.has_a + ob.has_b = 1
        ORDER BY o.pago_total DESC
        LIMIT ?
        """,
        [cliente_id, cliente_id, limit],
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6.5 Alertas: clientes valiosos en riesgo
# ─────────────────────────────────────────────────────────────────────────────

def clientes_urgentes() -> list[dict]:
    """MVPs / Alto Valor no single-buyers cuyo recency excede 1.5× su cadencia mediana.

    Renombrado desde clientes_en_riesgo() para diferenciar del segmento En Riesgo.
    El ratio usa GREATEST(dias_entre_compras, 1) para evitar división por cero en
    clientes B2B automatizados (cadencia 0 por compras múltiples diarias).
    """
    return fetch_dicts(
        """
        SELECT
          cliente_id,
          segmento_cluster                                       AS segmento,
          recency,
          dias_entre_compras                                     AS cadencia,
          recency::DOUBLE / GREATEST(dias_entre_compras, 1)      AS ratio,
          monetary,
          frequency
        FROM segmentos
        WHERE segmento_cluster IN ('MVPs', 'Alto Valor')
          AND es_single_buyer = 0
          AND dias_entre_compras >= 1
          AND recency > 1.5 * dias_entre_compras
        ORDER BY monetary DESC
        """
    )


def kpis_urgentes() -> dict:
    """KPIs de la tab Urgentes (MVPs + Alto Valor en riesgo individual)."""
    rows = fetch_dicts(
        """
        SELECT
          COUNT(*)                                                          AS n_total,
          SUM(CASE WHEN segmento_cluster = 'MVPs' THEN 1 ELSE 0 END)        AS n_mvps,
          SUM(CASE WHEN segmento_cluster = 'Alto Valor' THEN 1 ELSE 0 END)  AS n_alto,
          SUM(monetary)                                                     AS revenue_en_riesgo
        FROM segmentos
        WHERE segmento_cluster IN ('MVPs', 'Alto Valor')
          AND es_single_buyer = 0
          AND dias_entre_compras >= 1
          AND recency > 1.5 * dias_entre_compras
        """
    )
    return rows[0]


def clientes_reactivacion() -> list[dict]:
    """Clientes del segmento En Riesgo (no single-buyers), ordenados por monetary.

    A diferencia de clientes_urgentes(), aquí incluimos a todos los del segmento.
    El ratio sigue siendo útil para priorizar dentro del grupo (cuanto más alto,
    más tiempo lleva el cliente sin comprar respecto a su patrón histórico).
    """
    return fetch_dicts(
        """
        SELECT
          cliente_id,
          segmento_cluster                                       AS segmento,
          recency,
          dias_entre_compras                                     AS cadencia,
          recency::DOUBLE / GREATEST(dias_entre_compras, 1)      AS ratio,
          monetary,
          frequency
        FROM segmentos
        WHERE segmento_cluster = 'En Riesgo'
          AND es_single_buyer = 0
          AND dias_entre_compras >= 1
        ORDER BY monetary DESC
        """
    )


def kpis_reactivacion() -> dict:
    """KPIs de la tab Reactivación masiva (segmento En Riesgo)."""
    rows = fetch_dicts(
        """
        SELECT
          COUNT(*)                                AS n_total,
          SUM(monetary)                           AS revenue_potencial,
          MEDIAN(recency)                         AS recency_mediana,
          MEDIAN(dias_entre_compras)              AS cadencia_mediana
        FROM segmentos
        WHERE segmento_cluster = 'En Riesgo'
          AND es_single_buyer = 0
          AND dias_entre_compras >= 1
        """
    )
    return rows[0]


# Compatibilidad hacia atrás: nombres previos al SPEC de tabs en /alertas.
# Mantenidos como alias por si algún notebook o script externo los importa.
clientes_en_riesgo = clientes_urgentes
kpis_alertas = kpis_urgentes


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
    return bundles_top_por_segmento(segmento, modo="accionables")


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

def ranges_globales_por_segmento() -> dict:
    """
    Min/max de cada feature RFM medido sobre las MEDIANAS de los segmentos
    (no sobre clientes individuales). Esto replica el comportamiento del
    notebook v3 para el radar del comparador.
    """
    rows = fetch_dicts(
        """
        WITH medianas AS (
            SELECT
                segmento_cluster,
                MEDIAN(recency)            AS m_recency,
                MEDIAN(frequency)          AS m_frequency,
                MEDIAN(monetary)           AS m_monetary,
                MEDIAN(dias_entre_compras) AS m_cadencia
            FROM segmentos
            GROUP BY segmento_cluster
        )
        SELECT
            MIN(m_recency)   AS recency_min,   MAX(m_recency)   AS recency_max,
            MIN(m_frequency) AS frequency_min, MAX(m_frequency) AS frequency_max,
            MIN(m_monetary)  AS monetary_min,  MAX(m_monetary)  AS monetary_max,
            MIN(m_cadencia)  AS cadencia_min,  MAX(m_cadencia)  AS cadencia_max
        FROM medianas
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


# ─────────────────────────────────────────────────────────────────────────────
# 6.8 Movimientos: clientes en transición entre segmentos
# ─────────────────────────────────────────────────────────────────────────────

def clientes_en_frontera(threshold: float = 0.7) -> list[dict]:
    """Clientes cuya razón de distancias supera el threshold (cerca de la frontera)."""
    return fetch_dicts(
        """
        SELECT
          cliente_id,
          segmento_cluster                  AS segmento_actual,
          segmento_secundario,
          razon_distancias,
          recency,
          frequency,
          monetary,
          dias_entre_compras                AS cadencia,
          es_single_buyer
        FROM segmentos
        WHERE razon_distancias >= ?
          AND es_single_buyer = 0
        ORDER BY monetary DESC
        """,
        [threshold],
    )


def clientes_cambio_segmento(meses_atras: int = 1) -> list[dict]:
    """Clientes que cambiaron de segmento respecto al snapshot de N meses atrás."""
    from datetime import datetime

    from dateutil.relativedelta import relativedelta

    from pulse.config.paths import SNAPSHOTS_DIR

    fecha_target = datetime.now() - relativedelta(months=meses_atras)
    target_mes = fecha_target.strftime("%Y-%m")
    snapshot_path = SNAPSHOTS_DIR / f"snapshot_{target_mes}.parquet"

    if not snapshot_path.exists():
        return []

    from pulse.dashboard.db import get_connection
    con = get_connection()
    con.execute(
        f"CREATE OR REPLACE VIEW snapshot_anterior AS "
        f"SELECT * FROM read_parquet('{snapshot_path.as_posix()}')"
    )

    return fetch_dicts(
        """
        SELECT
          s.cliente_id,
          sa.segmento_cluster                AS segmento_anterior,
          s.segmento_cluster                 AS segmento_actual,
          s.recency,
          s.frequency,
          s.monetary,
          s.dias_entre_compras               AS cadencia,
          CASE
            WHEN sa.segmento_cluster = 'Hibernando' AND s.segmento_cluster IN ('Ocasionales', 'En Riesgo', 'Alto Valor', 'MVPs') THEN 'subida'
            WHEN sa.segmento_cluster = 'En Riesgo' AND s.segmento_cluster IN ('Ocasionales', 'Alto Valor', 'MVPs') THEN 'subida'
            WHEN sa.segmento_cluster = 'Ocasionales' AND s.segmento_cluster IN ('Alto Valor', 'MVPs') THEN 'subida'
            WHEN sa.segmento_cluster = 'Alto Valor' AND s.segmento_cluster = 'MVPs' THEN 'subida'
            ELSE 'bajada'
          END                                AS direccion
        FROM segmentos s
        JOIN snapshot_anterior sa USING (cliente_id)
        WHERE s.segmento_cluster != sa.segmento_cluster
          AND s.es_single_buyer = 0
        ORDER BY s.monetary DESC
        """
    )


def kpis_movimientos(
    frontera: list[dict] | None = None,
    cambios: list[dict] | None = None,
) -> dict:
    """KPIs de la vista Movimientos: en frontera + cambios de segmento del mes.

    Acepta `frontera` y `cambios` ya calculados para evitar releer el snapshot
    y recontar la frontera cuando el caller ya los obtuvo (router de la página).
    Si no se pasan, los calcula.
    """
    if frontera is None:
        frontera = clientes_en_frontera(threshold=0.7)
    if cambios is None:
        cambios = clientes_cambio_segmento(meses_atras=1)
    return {
        "n_en_frontera":   len(frontera),
        "n_subidas_mes":   sum(1 for c in cambios if c["direccion"] == "subida"),
        "n_bajadas_mes":   sum(1 for c in cambios if c["direccion"] == "bajada"),
        "n_total_cambios": len(cambios),
    }