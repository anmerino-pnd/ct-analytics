# SPEC v2: Alertas con Tabs, Drill-down Enriquecido y Vista Movimientos

**Versión:** 2.0 (reemplaza completamente v1)
**Autor:** Angel Merino
**Fecha:** Junio 2026
**Estado:** Listo para implementación

---

## Contexto

Esta es una iteración del SPEC original que incorpora tres cambios coordinados:

1. **Alertas con tabs** (Urgentes vs Reactivación masiva).
2. **Drill-down de cliente enriquecido** : en lugar de recomendar bundles MBA que el cliente no haya comprado (que en B2B con catálogo amplio es "aguja en pajar"), mostramos **bundles que el cliente ya forma en sus órdenes** y **oportunidades concretas** (órdenes donde compró parte del bundle pero no todo).
3. **Nueva vista "Movimientos"** : detecta clientes cuyo comportamiento está cambiando, vía dos señales: posición espacial cerca de la frontera entre clusters (K-Means + distance-to-centroid features) y trayectoria temporal mes a mes (snapshots mensuales).

Estos tres cambios se diseñaron juntos porque tocan los mismos archivos y forman una narrativa coherente del producto:  **detectar tanto los riesgos como las oportunidades** .

### Bibliografía relevante

* **B2B revenue growth** : McKinsey ("The B2B opportunity in customer experience") y BCG ("Profitable B2B growth") documentan que 70-80% del revenue incremental en B2B viene de profundización en cuentas existentes, no de nuevos productos. De ahí el cambio de enfoque del drill-down.
* **UX patterns** : Cooper et al., "About Face: The Essentials of Interaction Design" — vistas con modos mentales distintos requieren interfaces distintas. De ahí "Movimientos" como vista separada (no tab de Alertas).
* **Concept drift handling** : Gama et al. (2014), "A survey on concept drift adaptation"; Lu et al. (2019), "Learning under Concept Drift" — recomiendan re-entrenamiento por trigger de drift sobre snapshots históricos. De ahí los snapshots mensuales.

### Archivos involucrados

* `src/pulse/dashboard/queries.py`
* `src/pulse/dashboard/routers/api.py`
* `src/pulse/dashboard/routers/pages.py`
* `src/pulse/dashboard/templates/{alertas,cliente,movimientos}.html`
* `src/pulse/dashboard/templates/base.html` (link en navbar)
* `src/pulse/dashboard/db.py` (registrar vista de snapshots)
* `src/pulse/analytics/segmentacion.py` (agregar distancias a centroides)
* `src/pulse/pipeline/runner.py` (guardar snapshots mensuales)
* `src/pulse/config/paths.py` (path de snapshots)
* `src/pulse/modeling/segmentador.py` (exponer `cluster_names_ordered`)

---

## Cambio 1: Tabs en la vista de Alertas

### Problema actual

La vista `/dashboard/alertas` solo muestra clientes de los segmentos **MVPs** y **Alto Valor** cuya recency supera 1.5× su cadencia mediana. El segmento **En Riesgo** está excluido. Marketing necesita actuar sobre ambos grupos pero con estrategias distintas:

* **MVPs / Alto Valor con ratio > 1.5** : contacto directo, intervención de cuenta key, descuento personalizado. Lista corta, acción individual.
* **En Riesgo (todos)** : campaña masiva de reactivación, email marketing genérico. Lista larga, acción por grupos.

### Diseño

Modificar `/dashboard/alertas` para tener dos tabs:

1. **"Urgentes"** (default): MVPs y Alto Valor con ratio > 1.5.
2. **"Reactivación masiva"** : todo el segmento En Riesgo (excluyendo single-buyers y cadencia < 1).

### Cambios técnicos

#### 1.1 `src/pulse/dashboard/queries.py`

**Renombrar** `clientes_en_riesgo` → `clientes_urgentes` y `kpis_alertas` → `kpis_urgentes`. Cambiar `NULLIF(dias_entre_compras, 0)` por `GREATEST(dias_entre_compras, 1)` y agregar `dias_entre_compras >= 1` al WHERE (corrige los ratios infinitos que se ven hoy como ∞ en la tabla).

```python
def clientes_urgentes() -> list[dict]:
    """MVPs / Alto Valor no single-buyers cuyo recency excede 1.5× su cadencia mediana."""
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
    """Clientes del segmento En Riesgo (no single-buyers), ordenados por monetary."""
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
```

#### 1.2 `routers/api.py` y `routers/pages.py`

Endpoints API:

```python
@router.get("/alertas/urgentes")
async def alertas_urgentes() -> dict:
    return {"kpis": q.kpis_urgentes(), "clientes": q.clientes_urgentes()}


@router.get("/alertas/reactivacion")
async def alertas_reactivacion() -> dict:
    return {"kpis": q.kpis_reactivacion(), "clientes": q.clientes_reactivacion()}
```

Handler de página (pre-carga ambas tabs):

```python
@router.get("/alertas", response_class=HTMLResponse)
async def alertas(request: Request) -> HTMLResponse:
    initial_data = {
        "urgentes":     {"kpis": q.kpis_urgentes(),     "clientes": q.clientes_urgentes()},
        "reactivacion": {"kpis": q.kpis_reactivacion(), "clientes": q.clientes_reactivacion()},
    }
    ctx = _base_context("alertas")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "alertas.html", ctx)
```

#### 1.3 `templates/alertas.html`

```html
{% extends "base.html" %}
{% block title %}Alertas · Pulse{% endblock %}

{% block content %}
<header class="page-header">
  <h1>Clientes valiosos en riesgo</h1>
  <p class="subtitle">Acciones de retención y reactivación priorizadas por valor del cliente.</p>
</header>

<section class="filters">
  <div class="filter-group">
    <label>Vista</label>
    <div class="toggle-group" id="f-tab" role="tablist">
      <button data-tab="urgentes" class="active" type="button">Urgentes (acción individual)</button>
      <button data-tab="reactivacion" type="button">Reactivación masiva (En Riesgo)</button>
    </div>
  </div>
</section>

<!-- TAB: URGENTES -->
<div id="tab-urgentes" class="tab-content">
  <section class="kpi-grid">
    <div class="kpi-card"><span class="kpi-label">Total en riesgo</span><span class="kpi-value" id="kpi-urg-total">—</span></div>
    <div class="kpi-card"><span class="kpi-label">MVPs en riesgo</span><span class="kpi-value" id="kpi-urg-mvps">—</span></div>
    <div class="kpi-card"><span class="kpi-label">Alto Valor en riesgo</span><span class="kpi-value" id="kpi-urg-alto">—</span></div>
    <div class="kpi-card"><span class="kpi-label">Revenue en riesgo</span><span class="kpi-value" id="kpi-urg-revenue">—</span></div>
  </section>

  <section class="chart-card">
    <h2>Ratio de urgencia × monetary</h2>
    <div id="scatter-urgentes" class="chart"></div>
  </section>

  <section class="chart-card">
    <h2>Top clientes en riesgo (por monetary)</h2>
    <table class="data-table" id="tabla-urgentes">
      <thead>
        <tr>
          <th>Cliente</th><th>Segmento</th><th>Recency (d)</th>
          <th>Cadencia mediana</th><th>Ratio</th><th>Monetary</th>
          <th>Frequency</th><th></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </section>
</div>

<!-- TAB: REACTIVACIÓN -->
<div id="tab-reactivacion" class="tab-content hidden">
  <section class="kpi-grid">
    <div class="kpi-card"><span class="kpi-label">Total en En Riesgo</span><span class="kpi-value" id="kpi-rea-total">—</span></div>
    <div class="kpi-card"><span class="kpi-label">Revenue potencial recuperable</span><span class="kpi-value" id="kpi-rea-revenue">—</span></div>
    <div class="kpi-card"><span class="kpi-label">Recency mediana (días)</span><span class="kpi-value" id="kpi-rea-recency">—</span></div>
    <div class="kpi-card"><span class="kpi-label">Cadencia mediana original (días)</span><span class="kpi-value" id="kpi-rea-cadencia">—</span></div>
  </section>

  <section class="chart-card">
    <h2>Distribución de monetary × ratio</h2>
    <div id="scatter-reactivacion" class="chart"></div>
  </section>

  <section class="chart-card">
    <h2>Top clientes En Riesgo (por monetary histórico)</h2>
    <table class="data-table" id="tabla-reactivacion">
      <thead>
        <tr>
          <th>Cliente</th><th>Segmento</th><th>Recency (d)</th>
          <th>Cadencia mediana</th><th>Ratio</th><th>Monetary</th>
          <th>Frequency</th><th></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </section>
</div>

<details class="explainer">
  <summary>¿Qué estoy viendo?</summary>
  <div class="explainer-content">
    <p><strong>Urgentes</strong>: clientes MVPs y Alto Valor cuyo último pedido excede 1.5× su cadencia mediana habitual. Acción: contacto directo, descuento personalizado.</p>
    <p><strong>Reactivación masiva</strong>: clientes del segmento En Riesgo (todos llevan tiempo sin comprar respecto a su patrón histórico). Acción: campaña masiva con incentivos genéricos.</p>
  </div>
</details>

<script id="initial-data" type="application/json">{{ initial_data | tojson | safe }}</script>
{% endblock %}

{% block extra_scripts %}
<style>.tab-content.hidden { display: none; }</style>
<script>
  (function () {
    const initial = JSON.parse(document.getElementById('initial-data').textContent);
    const fmtNum = (v, d = 0) => v == null ? '—' : Number(v).toLocaleString('es-MX', { maximumFractionDigits: d });
    const fmtMoneda = (v) => v == null ? '—' : '$' + Math.round(v).toLocaleString('es-MX');

    function renderTab(tabName, data) {
      if (tabName === 'urgentes') {
        document.getElementById('kpi-urg-total').textContent   = fmtNum(data.kpis.n_total);
        document.getElementById('kpi-urg-mvps').textContent    = fmtNum(data.kpis.n_mvps);
        document.getElementById('kpi-urg-alto').textContent    = fmtNum(data.kpis.n_alto);
        document.getElementById('kpi-urg-revenue').textContent = fmtMoneda(data.kpis.revenue_en_riesgo);
        PulseCharts.renderScatterAlertas('scatter-urgentes', data.clientes.filter(c => c.ratio != null && isFinite(c.ratio)));
        renderTabla('tabla-urgentes', data.clientes);
      } else {
        document.getElementById('kpi-rea-total').textContent    = fmtNum(data.kpis.n_total);
        document.getElementById('kpi-rea-revenue').textContent  = fmtMoneda(data.kpis.revenue_potencial);
        document.getElementById('kpi-rea-recency').textContent  = fmtNum(data.kpis.recency_mediana);
        document.getElementById('kpi-rea-cadencia').textContent = fmtNum(data.kpis.cadencia_mediana);
        PulseCharts.renderScatterAlertas('scatter-reactivacion', data.clientes.filter(c => c.ratio != null && isFinite(c.ratio)));
        renderTabla('tabla-reactivacion', data.clientes);
      }
    }

    function renderTabla(tablaId, clientes) {
      const tbody = document.querySelector('#' + tablaId + ' tbody');
      tbody.innerHTML = '';
      clientes.forEach(c => {
        const color = window.SEGMENT_COLORS[c.segmento] || '#888';
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${c.cliente_id}</td>
          <td><span class="seg-chip" style="background:${color}"></span>${c.segmento}</td>
          <td>${fmtNum(c.recency)}</td>
          <td>${fmtNum(c.cadencia, 1)}</td>
          <td>${fmtNum(c.ratio, 2)}</td>
          <td>${fmtMoneda(c.monetary)}</td>
          <td>${fmtNum(c.frequency)}</td>
          <td><a href="/dashboard/cliente?id=${encodeURIComponent(c.cliente_id)}">Ver perfil →</a></td>
        `;
        tbody.appendChild(tr);
      });
    }

    renderTab('urgentes', initial.urgentes);
    renderTab('reactivacion', initial.reactivacion);

    document.querySelectorAll('#f-tab button').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#f-tab button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const tab = btn.dataset.tab;
        document.getElementById('tab-urgentes').classList.toggle('hidden', tab !== 'urgentes');
        document.getElementById('tab-reactivacion').classList.toggle('hidden', tab !== 'reactivacion');
      });
    });
  })();
</script>
{% endblock %}
```

---

## Cambio 2: Drill-down con bundles propios + oportunidades concretas

### Por qué este enfoque (no recomendaciones futuras)

En B2B con catálogos especializados, los clientes activos compran casi todas las familias relevantes para ellos. Recomendar "lo que no han comprado" produce listas vacías o irrelevantes. Por eso este SPEC cambia el enfoque a  **profundización** :

 **A. Top bundles propios** : pares de familias que el cliente ya compra juntos. Útil para entender su patrón de compra.

 **B. Oportunidades concretas** : órdenes específicas donde compró parte del bundle pero no toda. Cada fila es una oportunidad accionable directa: "en estas 3 órdenes el cliente compró A pero no B, históricamente compra ambas juntas en 32% de sus pedidos con A".

### 2.1 `queries.py` — Funciones nuevas

```python
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
    familia menos frecuente del par. Devuelve las órdenes con la oportunidad.
    """
    bundles_fuertes = fetch_dicts(
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
        )
        SELECT
            p.familia_a,
            p.familia_b,
            p.n_juntas,
            p.n_juntas * 1.0 / LEAST(ap_a.n_total, ap_b.n_total) AS co_occurrence
        FROM pares p
        JOIN apariciones ap_a ON ap_a.familia = p.familia_a
        JOIN apariciones ap_b ON ap_b.familia = p.familia_b
        WHERE p.n_juntas >= 2
          AND p.n_juntas * 1.0 / LEAST(ap_a.n_total, ap_b.n_total) >= 0.30
        """,
        [cliente_id],
    )

    if not bundles_fuertes:
        return []

    oportunidades = []
    for bundle in bundles_fuertes:
        fam_a, fam_b = bundle["familia_a"], bundle["familia_b"]

        # Órdenes con solo A (sin B)
        ords_solo_a = fetch_dicts(
            """
            SELECT
                o.order_id,
                strftime(o.fecha, '%Y-%m-%d %H:%M:%S')    AS fecha,
                o.pago_total
            FROM orders o
            WHERE o.cliente_id = ?
              AND o.order_id IN (
                  SELECT DISTINCT order_id FROM items
                  WHERE cliente_id = ? AND familia = ? AND clave != 'CARGO100'
              )
              AND o.order_id NOT IN (
                  SELECT DISTINCT order_id FROM items
                  WHERE cliente_id = ? AND familia = ? AND clave != 'CARGO100'
              )
            ORDER BY o.pago_total DESC
            """,
            [cliente_id, cliente_id, fam_a, cliente_id, fam_b],
        )
        for o in ords_solo_a:
            oportunidades.append({
                "order_id": o["order_id"], "fecha": o["fecha"],
                "pago_total": o["pago_total"],
                "compro": fam_a, "le_falto": fam_b,
                "co_occurrence": bundle["co_occurrence"],
            })

        # Órdenes con solo B (sin A)
        ords_solo_b = fetch_dicts(
            """
            SELECT
                o.order_id,
                strftime(o.fecha, '%Y-%m-%d %H:%M:%S')    AS fecha,
                o.pago_total
            FROM orders o
            WHERE o.cliente_id = ?
              AND o.order_id IN (
                  SELECT DISTINCT order_id FROM items
                  WHERE cliente_id = ? AND familia = ? AND clave != 'CARGO100'
              )
              AND o.order_id NOT IN (
                  SELECT DISTINCT order_id FROM items
                  WHERE cliente_id = ? AND familia = ? AND clave != 'CARGO100'
              )
            ORDER BY o.pago_total DESC
            """,
            [cliente_id, cliente_id, fam_b, cliente_id, fam_a],
        )
        for o in ords_solo_b:
            oportunidades.append({
                "order_id": o["order_id"], "fecha": o["fecha"],
                "pago_total": o["pago_total"],
                "compro": fam_b, "le_falto": fam_a,
                "co_occurrence": bundle["co_occurrence"],
            })

    oportunidades.sort(key=lambda x: x["pago_total"] or 0, reverse=True)
    return oportunidades[:limit]
```

### 2.2 Endpoint extendido

```python
@router.get("/cliente/{cliente_id}")
async def cliente_drilldown(cliente_id: str) -> dict:
    perfil = q.cliente_perfil(cliente_id)
    if perfil is None:
        raise HTTPException(status_code=404, detail=f"Cliente '{cliente_id}' no encontrado")
    return {
        "perfil":          perfil,
        "pedidos":         q.cliente_pedidos(cliente_id, limit=50),
        "posicion":        q.cliente_posicion_segmento(cliente_id),
        "productos_top":   q.cliente_productos_top(cliente_id, limit=10),
        "bundles_propios": q.cliente_bundles_propios(cliente_id, limit=10),
        "oportunidades":   q.cliente_oportunidades(cliente_id, limit=10),
    }
```

### 2.3 Template — tres secciones nuevas

Reemplazar la sección de "Recomendaciones" del SPEC v1 (si existía) por tres secciones nuevas en `cliente.html` después del scatter de posición:

```html
<section class="chart-card">
  <h2>Top productos del cliente</h2>
  <p class="subtitle" id="prod-summary">—</p>
  <table class="data-table" id="tabla-productos">
    <thead>
      <tr><th>Familia</th><th>N° pedidos</th><th>Unidades</th><th>Revenue total</th><th>Última compra</th></tr>
    </thead>
    <tbody></tbody>
  </table>
</section>

<section class="chart-card">
  <h2>Bundles que el cliente compra juntos</h2>
  <p class="subtitle">
    Pares de familias en las mismas órdenes. <em>Conf./Lift segmento</em> indica si
    el bundle también es regla accionable del segmento del cliente.
  </p>
  <table class="data-table" id="tabla-bundles-propios">
    <thead>
      <tr><th>Familia A</th><th>Familia B</th><th>N° órdenes juntas</th>
          <th>% de órdenes del cliente</th><th>Conf. segmento</th><th>Lift segmento</th></tr>
    </thead>
    <tbody></tbody>
  </table>
</section>

<section class="chart-card">
  <h2>Oportunidades de cross-sell detectadas</h2>
  <p class="subtitle">
    Órdenes donde el cliente compró una parte de uno de sus bundles habituales
    pero no la otra. Cada fila es una oportunidad de empuje concreta.
  </p>
  <table class="data-table" id="tabla-oportunidades">
    <thead>
      <tr><th>Order ID</th><th>Fecha</th><th>Pago total</th>
          <th>Compró</th><th>Le faltó</th><th>Co-ocurrencia histórica</th></tr>
    </thead>
    <tbody></tbody>
  </table>
</section>
```

JS para renderizar (dentro del template, agregar al final del bloque que ya pinta `renderCliente`):

```javascript
// Top productos
const tbodyProd = document.querySelector('#tabla-productos tbody');
tbodyProd.innerHTML = '';
data.productos_top.forEach(p => {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><code>${p.familia}</code></td>
    <td>${fmtNum(p.n_pedidos)}</td>
    <td>${fmtNum(p.unidades_totales)}</td>
    <td>${fmtMoneda(p.revenue_total)}</td>
    <td>${p.ultima_compra ? p.ultima_compra.substring(0, 10) : '—'}</td>
  `;
  tbodyProd.appendChild(tr);
});
document.getElementById('prod-summary').textContent =
  data.productos_top.length + ' familias compradas (top por revenue).';

// Bundles propios
const tbodyBP = document.querySelector('#tabla-bundles-propios tbody');
tbodyBP.innerHTML = '';
if (data.bundles_propios.length === 0) {
  tbodyBP.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-soft)">Sin bundles detectados (cliente con pocas órdenes multi-familia).</td></tr>';
} else {
  data.bundles_propios.forEach(b => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${b.familia_a}</code></td>
      <td><code>${b.familia_b}</code></td>
      <td>${fmtNum(b.n_ordenes)}</td>
      <td>${fmtPct(b.pct_aparicion)}</td>
      <td>${b.confidence_segmento != null ? fmtPct(b.confidence_segmento) : '—'}</td>
      <td>${b.lift_segmento != null ? fmtNum(b.lift_segmento, 2) : '—'}</td>
    `;
    tbodyBP.appendChild(tr);
  });
}

// Oportunidades
const tbodyOp = document.querySelector('#tabla-oportunidades tbody');
tbodyOp.innerHTML = '';
if (data.oportunidades.length === 0) {
  tbodyOp.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-soft)">Sin oportunidades detectadas. El cliente cierra consistentemente sus bundles.</td></tr>';
} else {
  data.oportunidades.forEach(o => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${o.order_id}</code></td>
      <td>${o.fecha}</td>
      <td>${fmtMoneda(o.pago_total)}</td>
      <td><code>${o.compro}</code></td>
      <td><code>${o.le_falto}</code></td>
      <td>${fmtPct(o.co_occurrence)}</td>
    `;
    tbodyOp.appendChild(tr);
  });
}
```

---

## Cambio 3: Vista "Movimientos" — clientes en transición

### Concepto

Vista nueva (`/dashboard/movimientos`) que detecta clientes cuyo comportamiento está cambiando. Dos señales:

1. **Espacial** : clientes cuya distancia al segundo cluster más cercano es similar a la del propio (`razon_distancias >= 0.7`). Están "en frontera".
2. **Temporal** : clientes que cambiaron de segmento entre el snapshot del mes pasado y el actual.

**Vista separada (no tab de Alertas)** porque el modo mental es opuesto: Alertas = retención reactiva; Movimientos = oportunidad proactiva. Cooper et al. recomiendan no mezclar contextos en tabs.

### 3.1 `analytics/segmentacion.py` — agregar distancias

La función `segmentar_clientes()` actualmente devuelve `cliente_id, cluster_id, segmento_cluster`. Agregar 4 columnas más después del `predict()`:

```python
import numpy as np

# Aplicar log_transform + scaler manualmente para obtener features escaladas
pipeline = modelo.pipeline
features_array = df_rfm[feature_cols].values
features_transformed = pipeline.named_steps['scaler'].transform(
    pipeline.named_steps['log_transform'].transform(features_array)
)

# Distancias a todos los centroides
centroides = pipeline.named_steps['kmeans'].cluster_centers_  # shape (k, n_features)
distancias = np.linalg.norm(
    features_transformed[:, np.newaxis, :] - centroides[np.newaxis, :, :],
    axis=2
)  # shape (n_clientes, k)

# Sort para obtener primer y segundo centroide más cercano
sorted_idx = np.argsort(distancias, axis=1)
dist_propia = np.take_along_axis(distancias, sorted_idx[:, :1], axis=1).flatten()
dist_segunda = np.take_along_axis(distancias, sorted_idx[:, 1:2], axis=1).flatten()
seg_secundario_idx = sorted_idx[:, 1]

# Mapear índice a nombre — requiere cluster_names_ordered en SegmentadorClientes
cluster_names = modelo.cluster_names_ordered  # lista de nombres en orden de centroides
segmento_secundario = [cluster_names[i] for i in seg_secundario_idx]

df_resultado["distancia_propia"]    = dist_propia
df_resultado["distancia_segunda"]   = dist_segunda
df_resultado["razon_distancias"]    = dist_propia / dist_segunda
df_resultado["segmento_secundario"] = segmento_secundario
```

> [!NOTE]
> Si `cluster_names_ordered` no existe en `modeling/segmentador.py`, agregarlo: una lista que se construya durante el `fit()` y se guarde en `metadata.json` para que tras `load()` esté disponible.

### 3.2 `pipeline/runner.py` — snapshots mensuales

En el flujo del runner, cuando `modo == "monthly"`, después del paso de segmentación, llamar:

```python
from datetime import datetime
from pulse.config.paths import SNAPSHOTS_DIR

def guardar_snapshot_mensual(df_segmentados: pd.DataFrame) -> None:
    """Guarda snapshot del estado actual de segmentación mes a mes.

    Path: datos/processed/snapshots/snapshot_YYYY-MM.parquet.
    Idempotente: sobreescribe si ya existe el snapshot del mismo mes.
    """
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    mes = datetime.now().strftime("%Y-%m")
    path = SNAPSHOTS_DIR / f"snapshot_{mes}.parquet"
    df_segmentados[
        ["cliente_id", "segmento_cluster", "recency", "frequency",
         "monetary", "dias_entre_compras", "razon_distancias"]
    ].to_parquet(path, index=False)
    log.info(f"✅ Snapshot mensual guardado: {path.name}")
```

### 3.3 `config/paths.py`

```python
SNAPSHOTS_DIR = PROCESSED / "snapshots"
```

### 3.4 `queries.py` — funciones para Movimientos

```python
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


def kpis_movimientos() -> dict:
    en_frontera = fetch_dicts(
        "SELECT COUNT(*) AS n FROM segmentos WHERE razon_distancias >= 0.7 AND es_single_buyer = 0"
    )
    cambios = clientes_cambio_segmento(meses_atras=1)
    return {
        "n_en_frontera":   en_frontera[0]["n"],
        "n_subidas_mes":   sum(1 for c in cambios if c["direccion"] == "subida"),
        "n_bajadas_mes":   sum(1 for c in cambios if c["direccion"] == "bajada"),
        "n_total_cambios": len(cambios),
    }
```

### 3.5 Routers

```python
# api.py
@router.get("/movimientos")
async def movimientos() -> dict:
    return {
        "kpis":     q.kpis_movimientos(),
        "frontera": q.clientes_en_frontera(threshold=0.7),
        "cambios":  q.clientes_cambio_segmento(meses_atras=1),
    }

# pages.py
@router.get("/movimientos", response_class=HTMLResponse)
async def movimientos(request: Request) -> HTMLResponse:
    initial_data = {
        "kpis":     q.kpis_movimientos(),
        "frontera": q.clientes_en_frontera(threshold=0.7),
        "cambios":  q.clientes_cambio_segmento(meses_atras=1),
    }
    ctx = _base_context("movimientos")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "movimientos.html", ctx)
```

### 3.6 `templates/base.html` — agregar nav

```html
<a href="/dashboard/movimientos"
   class="nav-link {% if vista_activa == 'movimientos' %}active{% endif %}">Movimientos</a>
```

### 3.7 `templates/movimientos.html`

```html
{% extends "base.html" %}
{% block title %}Movimientos · Pulse{% endblock %}

{% block content %}
<header class="page-header">
  <h1>Movimientos entre segmentos</h1>
  <p class="subtitle">
    Clientes cuyo comportamiento está cambiando: detectados por trayectoria temporal
    (cambio de segmento mes a mes) o por posición espacial (cerca de la frontera entre clusters).
  </p>
</header>

<section class="kpi-grid">
  <div class="kpi-card"><span class="kpi-label">Clientes en frontera</span><span class="kpi-value" id="kpi-frontera">—</span></div>
  <div class="kpi-card"><span class="kpi-label">Subidas (mes actual)</span><span class="kpi-value" id="kpi-subidas">—</span></div>
  <div class="kpi-card"><span class="kpi-label">Bajadas (mes actual)</span><span class="kpi-value" id="kpi-bajadas">—</span></div>
  <div class="kpi-card"><span class="kpi-label">Total cambios</span><span class="kpi-value" id="kpi-cambios">—</span></div>
</section>

<section class="chart-card">
  <h2>Cambios de segmento (mes a mes)</h2>
  <p class="subtitle">
    Clientes en un segmento distinto al de hace un mes.
    <em>Subidas</em> = movimientos hacia segmentos de mayor valor.
    <em>Bajadas</em> = deterioro temprano (antes de Alertas).
  </p>
  <table class="data-table" id="tabla-cambios">
    <thead>
      <tr><th>Cliente</th><th>Segmento anterior</th><th>Segmento actual</th>
          <th>Dirección</th><th>Monetary</th><th>Frequency</th><th></th></tr>
    </thead>
    <tbody></tbody>
  </table>
</section>

<section class="chart-card">
  <h2>Clientes en frontera entre clusters</h2>
  <p class="subtitle">
    Clientes cuya distancia al segundo cluster más cercano es similar a la del propio.
    Razón ≥ 0.7 indica que el cliente podría pertenecer a cualquiera de los dos.
  </p>
  <table class="data-table" id="tabla-frontera">
    <thead>
      <tr><th>Cliente</th><th>Segmento actual</th><th>Segmento secundario</th>
          <th>Razón distancias</th><th>Monetary</th><th>Frequency</th><th></th></tr>
    </thead>
    <tbody></tbody>
  </table>
</section>

<details class="explainer">
  <summary>¿Qué estoy viendo?</summary>
  <div class="explainer-content">
    <p><strong>Cambios de segmento</strong>: el modelo asigna cada cliente a su cluster basado en RFM + cadencia actuales. Si el comportamiento cambia, la próxima corrida lo reasigna automáticamente. Esta tabla muestra los reasignados respecto al snapshot del mes pasado.</p>
    <p><strong>Clientes en frontera</strong>: K-Means asigna al cluster con centroide más cercano, pero algunos clientes están en zonas ambiguas. Razón cerca de 1.0 = en la frontera.</p>
    <p><strong>Acción</strong>: subidas → profundizar la cuenta. Bajadas → intervención preventiva. Frontera → vigilar y empujar al mejor segmento.</p>
  </div>
</details>

<script id="initial-data" type="application/json">{{ initial_data | tojson | safe }}</script>
{% endblock %}

{% block extra_scripts %}
<script>
  (function () {
    const data = JSON.parse(document.getElementById('initial-data').textContent);
    const fmtNum = (v, d = 0) => v == null ? '—' : Number(v).toLocaleString('es-MX', { maximumFractionDigits: d });
    const fmtMoneda = (v) => v == null ? '—' : '$' + Math.round(v).toLocaleString('es-MX');

    document.getElementById('kpi-frontera').textContent = fmtNum(data.kpis.n_en_frontera);
    document.getElementById('kpi-subidas').textContent  = fmtNum(data.kpis.n_subidas_mes);
    document.getElementById('kpi-bajadas').textContent  = fmtNum(data.kpis.n_bajadas_mes);
    document.getElementById('kpi-cambios').textContent  = fmtNum(data.kpis.n_total_cambios);

    const tbodyC = document.querySelector('#tabla-cambios tbody');
    if (data.cambios.length === 0) {
      tbodyC.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-soft)">Sin snapshot del mes anterior disponible. El primer mes tras implementar el sistema no tiene base de comparación.</td></tr>';
    } else {
      data.cambios.forEach(c => {
        const colorAnt = window.SEGMENT_COLORS[c.segmento_anterior] || '#888';
        const colorAct = window.SEGMENT_COLORS[c.segmento_actual] || '#888';
        const dirIcon = c.direccion === 'subida' ? '↑' : '↓';
        const dirColor = c.direccion === 'subida' ? '#0B7332' : '#D82822';
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${c.cliente_id}</td>
          <td><span class="seg-chip" style="background:${colorAnt}"></span>${c.segmento_anterior}</td>
          <td><span class="seg-chip" style="background:${colorAct}"></span>${c.segmento_actual}</td>
          <td style="color:${dirColor};font-weight:bold">${dirIcon} ${c.direccion}</td>
          <td>${fmtMoneda(c.monetary)}</td>
          <td>${fmtNum(c.frequency)}</td>
          <td><a href="/dashboard/cliente?id=${encodeURIComponent(c.cliente_id)}">Ver perfil →</a></td>
        `;
        tbodyC.appendChild(tr);
      });
    }

    const tbodyF = document.querySelector('#tabla-frontera tbody');
    data.frontera.forEach(c => {
      const colorAct = window.SEGMENT_COLORS[c.segmento_actual] || '#888';
      const colorSec = window.SEGMENT_COLORS[c.segmento_secundario] || '#888';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${c.cliente_id}</td>
        <td><span class="seg-chip" style="background:${colorAct}"></span>${c.segmento_actual}</td>
        <td><span class="seg-chip" style="background:${colorSec}"></span>${c.segmento_secundario}</td>
        <td>${fmtNum(c.razon_distancias, 3)}</td>
        <td>${fmtMoneda(c.monetary)}</td>
        <td>${fmtNum(c.frequency)}</td>
        <td><a href="/dashboard/cliente?id=${encodeURIComponent(c.cliente_id)}">Ver perfil →</a></td>
      `;
      tbodyF.appendChild(tr);
    });
  })();
</script>
{% endblock %}
```

---

## Testing

```python
def test_clientes_urgentes_excluye_single_buyers():
    from pulse.dashboard.queries import clientes_urgentes
    segmentos = {r["segmento"] for r in clientes_urgentes()}
    assert segmentos.issubset({"MVPs", "Alto Valor"})


def test_clientes_reactivacion_solo_en_riesgo():
    from pulse.dashboard.queries import clientes_reactivacion
    segmentos = {r["segmento"] for r in clientes_reactivacion()}
    assert segmentos == {"En Riesgo"} or len(segmentos) == 0


def test_ratio_no_es_infinito():
    from pulse.dashboard.queries import clientes_urgentes, clientes_reactivacion
    import math
    for fn in [clientes_urgentes, clientes_reactivacion]:
        for r in fn():
            assert r["ratio"] is not None and math.isfinite(r["ratio"])


def test_cliente_bundles_propios_orden_lexicografico():
    from pulse.dashboard.queries import cliente_bundles_propios
    for r in cliente_bundles_propios("PAC0751", limit=10):
        assert r["familia_a"] < r["familia_b"]


def test_cliente_oportunidades_estructura():
    from pulse.dashboard.queries import cliente_oportunidades
    for r in cliente_oportunidades("PAC0751", limit=10):
        assert "compro" in r and "le_falto" in r
        assert r["compro"] != r["le_falto"]


def test_clientes_en_frontera_threshold():
    from pulse.dashboard.queries import clientes_en_frontera
    for r in clientes_en_frontera(threshold=0.7):
        assert r["razon_distancias"] >= 0.7


def test_segmentador_devuelve_distancias():
    """El segmentador debe agregar las 4 columnas nuevas."""
    from pulse.analytics.segmentacion import segmentar_clientes
    import pandas as pd
    df_rfm = pd.read_parquet("datos/processed/clientes_segmentados.parquet")
    df_seg = segmentar_clientes(df_rfm)
    for col in ["distancia_propia", "distancia_segunda", "razon_distancias", "segmento_secundario"]:
        assert col in df_seg.columns
    assert (df_seg["razon_distancias"] >= 0).all()
    assert (df_seg["razon_distancias"] <= 1.0001).all()
```

### Smoke test manual

1. Correr `uv run python -m pulse.pipeline monthly` para regenerar parquets y crear primer snapshot.
2. Arrancar dashboard: `uv run uvicorn pulse.dashboard.app:app --reload`.
3. Verificar:
   * `/dashboard/alertas` → dos tabs funcionando.
   * `/dashboard/cliente?id=PAC0751` → secciones Productos + Bundles propios + Oportunidades.
   * `/dashboard/movimientos` → KPIs + tabla frontera poblada. Tabla cambios vacía el primer mes (esperado).
4. Después del segundo mes (o forzando un snapshot anterior), volver a Movimientos: tabla cambios poblada.

---

## Lo que NO está en este SPEC

* **Re-entrenamiento automático del modelo `v2`** . Sigue manual. Movimientos da los insumos para decidir cuándo, no lo hace solo.
* **Visualización de trayectoria temporal del cliente** (timeline de cambios en su drill-down). Iteración futura.
* **Modelo de propensity to migrate** (predicción de movimiento futuro). Fase 5+.
* **Paginación de tabla Reactivación** (~3,500 filas). Si causa lag visual, se agrega después.

---

## Orden de implementación

1. **Pipeline analítico** : modificar `segmentador.py` (agregar `cluster_names_ordered`), `segmentacion.py` (distancias), `runner.py` (snapshots), `paths.py` (SNAPSHOTS_DIR). Correr `uv run pytest tests/test_segmentacion.py`.
2. **Regenerar parquets** : `uv run python -m pulse.pipeline monthly`. Verifica que `clientes_segmentados.parquet` tiene las nuevas columnas y existe el primer snapshot.
3. **Cambio 1 (Alertas tabs)** : queries + api + pages + template.
4. **Cambio 2 (Drill-down enriquecido)** : queries + api + template.
5. **Cambio 3 (Vista Movimientos)** : queries + api + pages + template nuevo + nav.
6. **Tests nuevos** + verificar que todos pasan.
7. **Smoke test manual** local.
8. **Deploy** : commit, push, en servidor `git pull && sudo systemctl restart pulse-dashboard`.

---

## Definición de "Hecho"

* [ ] `SegmentadorClientes` expone `cluster_names_ordered`.
* [ ] `segmentar_clientes()` devuelve las 4 columnas nuevas.
* [ ] `runner.py` modo `monthly` persiste snapshots idempotentes.
* [ ] Bug del ratio infinito (`NULLIF` → `GREATEST`) corregido.
* [ ] `/dashboard/alertas` tiene dos tabs funcionales.
* [ ] `/dashboard/cliente` muestra tres tablas: productos, bundles propios, oportunidades.
* [ ] `/dashboard/movimientos` carga con KPIs + dos tablas.
* [ ] Nav actualizado.
* [ ] Tests nuevos pasan (`uv run pytest`).
* [ ] Smoke test manual sin errores.
* [ ] Deploy a producción exitoso.
