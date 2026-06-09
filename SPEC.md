# SPEC: Tendencia diaria — vista "Último mes" en evolución temporal

**Versión:** 1.0
**Autor:** Angel Merino
**Fecha:** Junio 2026
**Estado:** Listo para implementación

---

## Contexto

La gráfica "Evolución mensual de pedidos" en `/dashboard/estacionalidad` muestra 30 meses de histórico. Para detección de tendencias macro funciona, pero para responder **"¿cómo vamos este mes?"** es ciega: el mes en curso aparece como un punto bajo (porque solo lleva N días), sin contexto comparativo.

Marketing necesita una vista complementaria que responda:

1. ¿Cómo va este mes día a día?
2. ¿Vamos arriba o abajo del mismo periodo del mes anterior?
3. ¿Qué segmentos están acelerando o desacelerando?

### Diseño

Agregar un **toggle** sobre la gráfica de evolución con dos modos:

* **"Histórico mensual"** (default, comportamiento actual): 30 meses agregados.
* **"Último mes"** : línea diaria del mes en curso superpuesta con la línea diaria del mismo rango del mes anterior. KPIs de variación.

### Decisiones tomadas

* **Granularidad nueva** : diaria, en un parquet `temp_diario.parquet`.
* **Ventana de "último mes"** : del día 1 del mes en curso hasta hoy.
* **Comparación** : contra el mismo rango de días del mes anterior. Si hoy es 9 de junio, comparamos junio 1-9 vs mayo 1-9.
* **Frecuencia de regeneración** : el parquet `temp_diario.parquet` se regenera en cada corrida `daily`. Costo adicional <5s.
* **Ventana del parquet diario** : últimos 90 días (no 30 meses como el mensual, sería desperdicio).
* **Segmentos visibles** : los 5 segmentos como líneas separadas.
* **KPIs** : 6 cards arriba de la gráfica con variación de pedidos por segmento + 1 total.

### Archivos afectados

* `src/pulse/analytics/temporalidad.py` — nueva función `calcular_temp_diario()`.
* `src/pulse/pipeline/runner.py` — agregar paso de generación del parquet diario.
* `src/pulse/pipeline/validacion.py` — quality check del nuevo parquet.
* `src/pulse/dashboard/db.py` — registrar nueva vista DuckDB.
* `src/pulse/dashboard/queries.py` — 3 funciones nuevas.
* `src/pulse/dashboard/routers/api.py` — nuevo endpoint.
* `src/pulse/dashboard/routers/pages.py` — modificar handler de estacionalidad.
* `src/pulse/dashboard/templates/estacionalidad.html` — toggle + nuevo bloque.
* `src/pulse/dashboard/static/js/charts.js` — funciones nuevas para gráfica diaria.
* `tests/test_temporalidad.py` — tests nuevos.

---

## Cambio 1: Pipeline analítico — agregado diario

### 1.1 Nueva función en `src/pulse/analytics/temporalidad.py`

Agregar después de las funciones de agregado mensual existentes:

```python
def calcular_temp_diario(
    df_orders: pd.DataFrame,
    df_segmentos: pd.DataFrame,
    fecha_ref: pd.Timestamp | None = None,
    dias_atras: int = 90,
) -> pd.DataFrame:
    """Agregado diario de pedidos por segmento.

    Se limita a una ventana corta (default 90 días) porque solo se consume
    para la vista 'Último mes' del dashboard.

    Args:
        df_orders: pedidos en la ventana (post-filtro CARGO100).
            Debe tener: order_id, cliente_id, fecha (UTC), pago_total.
        df_segmentos: cliente_id, segmento_cluster.
        fecha_ref: fecha de referencia (default: ahora UTC).
        dias_atras: cuántos días incluir hacia atrás desde fecha_ref.

    Returns:
        DataFrame con: fecha_dia (date), segmento (str), pedidos (int), revenue (float).
    """
    if fecha_ref is None:
        fecha_ref = pd.Timestamp.now(tz="UTC")

    fecha_corte = fecha_ref - pd.Timedelta(days=dias_atras)

    orders_recientes = df_orders[df_orders["fecha"] >= fecha_corte].copy()

    orders_recientes["fecha_local"] = orders_recientes["fecha"].dt.tz_convert(
        "America/Mexico_City"
    )
    orders_recientes["fecha_dia"] = orders_recientes["fecha_local"].dt.date

    orders_seg = orders_recientes.merge(
        df_segmentos[["cliente_id", "segmento_cluster"]],
        on="cliente_id",
        how="inner",
    )

    if orders_seg.empty:
        return pd.DataFrame(columns=["fecha_dia", "segmento", "pedidos", "revenue"])

    agregado = (
        orders_seg
        .groupby(["fecha_dia", "segmento_cluster"], as_index=False)
        .agg(
            pedidos=("order_id", "count"),
            revenue=("pago_total", "sum"),
        )
        .rename(columns={"segmento_cluster": "segmento"})
    )

    return agregado.sort_values(["fecha_dia", "segmento"]).reset_index(drop=True)
```

### 1.2 Integración en `src/pulse/pipeline/runner.py`

Localizar el paso de "Temporalidad" y agregar la generación del agregado diario después de los otros agregados:

```python
from pulse.analytics.temporalidad import calcular_temp_diario

log.info("    Generando temp_diario...")
df_temp_diario = calcular_temp_diario(
    df_orders=df_orders_filtrado,
    df_segmentos=df_segmentos,
    dias_atras=90,
)
df_temp_diario.to_parquet(PROCESSED / "temp_diario.parquet", index=False)
log.info(f"    ✅ Temp diario guardado: {len(df_temp_diario)} filas")
```

### 1.3 Quality check en `src/pulse/pipeline/validacion.py`

```python
def validar_temp_diario(df_temp_diario: pd.DataFrame) -> None:
    """Verifica que temp_diario tiene datos razonables.

    No hacemos cross-check exacto contra RFM porque temp_diario solo cubre
    los últimos 90 días, mientras RFM cubre la ventana completa de 30 meses.
    """
    if df_temp_diario.empty:
        raise QualityError("temp_diario está vacío — sin pedidos en los últimos 90 días")

    pedidos_total = df_temp_diario["pedidos"].sum()
    if pedidos_total < 100:
        raise QualityError(
            f"temp_diario tiene solo {pedidos_total} pedidos en 90 días — anómalo"
        )

    n_segmentos_unicos = df_temp_diario["segmento"].nunique()
    if n_segmentos_unicos < 3:
        raise QualityError(
            f"temp_diario tiene solo {n_segmentos_unicos} segmentos únicos — esperamos al menos 3"
        )

    log.info(
        f"✅ temp_diario OK ({pedidos_total:,} pedidos en "
        f"{df_temp_diario['fecha_dia'].nunique()} días, "
        f"{n_segmentos_unicos} segmentos)"
    )
```

Llamar después de generar el parquet en `runner.py`.

---

## Cambio 2: Dashboard — DuckDB y queries

### 2.1 `src/pulse/dashboard/db.py`

Agregar al setup de DuckDB:

```python
con.execute("""
    CREATE OR REPLACE VIEW temp_diario AS
    SELECT * FROM read_parquet(?)
""", [str(PROCESSED / "temp_diario.parquet")])
```

### 2.2 `src/pulse/dashboard/queries.py`

Tres funciones nuevas:

```python
def temp_diario_ultimo_mes() -> list[dict]:
    """Datos diarios del mes en curso, por segmento."""
    return fetch_dicts(
        """
        SELECT fecha_dia, segmento, pedidos, revenue
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
        SELECT fecha_dia, segmento, pedidos, revenue
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
```

---

## Cambio 3: API y handler de página

### 3.1 `src/pulse/dashboard/routers/api.py`

```python
@router.get("/estacionalidad/ultimo-mes")
async def estacionalidad_ultimo_mes() -> dict:
    return {
        "actual":   q.temp_diario_ultimo_mes(),
        "anterior": q.temp_diario_mes_anterior_mismo_rango(),
        "kpis":     q.kpis_variacion_mensual(),
    }
```

### 3.2 `src/pulse/dashboard/routers/pages.py`

Modificar el handler de `/dashboard/estacionalidad` para pre-cargar ambos modos:

```python
@router.get("/estacionalidad", response_class=HTMLResponse)
async def estacionalidad(request: Request) -> HTMLResponse:
    initial_data = {
        "historico": {
            "hora_dia": q.temp_hora_dia(),
            "mensual":  q.temp_mensual(),
        },
        "ultimo_mes": {
            "actual":   q.temp_diario_ultimo_mes(),
            "anterior": q.temp_diario_mes_anterior_mismo_rango(),
            "kpis":     q.kpis_variacion_mensual(),
        },
    }
    ctx = _base_context("estacionalidad")
    ctx["initial_data"] = initial_data
    return templates.TemplateResponse(request, "estacionalidad.html", ctx)
```

---

## Cambio 4: Template `estacionalidad.html`

Agregar antes de la gráfica de evolución mensual existente:

```html
<section class="chart-card">
  <div class="card-header">
    <h2>Evolución de pedidos</h2>
    <div class="toggle-group" id="f-modo-temporal" role="tablist">
      <button data-modo="historico" class="active" type="button">Histórico mensual</button>
      <button data-modo="ultimo-mes" type="button">Último mes</button>
    </div>
  </div>

  <!-- Modo: histórico (default) -->
  <div id="modo-historico" class="modo-content">
    <div id="grafica-evolucion-mensual" class="chart"></div>
  </div>

  <!-- Modo: último mes -->
  <div id="modo-ultimo-mes" class="modo-content hidden">
    <div class="kpi-grid" id="kpis-variacion">
      <!-- Generados dinámicamente -->
    </div>
    <div id="grafica-evolucion-diaria" class="chart"></div>
    <p class="subtitle" style="margin-top: 8px;">
      Líneas continuas: <strong>mes en curso</strong>.
      Líneas punteadas: <strong>mismo rango del mes anterior</strong>.
      Las KPIs comparan el total acumulado hasta hoy vs el mismo número de días del mes anterior.
    </p>
  </div>
</section>
```

CSS al final del template o en `styles.css`:

```css
.modo-content.hidden { display: none; }
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.kpi-variacion-up   { color: #0B7332; font-weight: 600; }
.kpi-variacion-down { color: #D82822; font-weight: 600; }
.kpi-variacion-flat { color: var(--text-soft); }
```

---

## Cambio 5: JS de gráfica diaria

En `src/pulse/dashboard/static/js/charts.js`, agregar:

```javascript
function renderEvolucionDiaria(containerId, datosActual, datosAnterior) {
  const segmentos = [...new Set(datosActual.map(d => d.segmento))];

  const traces = [];

  segmentos.forEach(seg => {
    const datosSegActual = datosActual.filter(d => d.segmento === seg);
    traces.push({
      x: datosSegActual.map(d => d.fecha_dia),
      y: datosSegActual.map(d => d.pedidos),
      name: seg + ' (actual)',
      mode: 'lines+markers',
      line: { color: SEGMENT_COLORS[seg], width: 2.5 },
      legendgroup: seg,
    });

    // Mes anterior: alineado al mismo día relativo del mes en curso
    const datosSegAnt = datosAnterior.filter(d => d.segmento === seg);
    traces.push({
      x: datosSegAnt.map((_, i) => datosSegActual[i]?.fecha_dia || null).filter(Boolean),
      y: datosSegAnt.map(d => d.pedidos),
      name: seg + ' (mes anterior)',
      mode: 'lines',
      line: { color: SEGMENT_COLORS[seg], width: 1.5, dash: 'dot' },
      legendgroup: seg,
      showlegend: false,
    });
  });

  Plotly.newPlot(containerId, traces, {
    template: 'simple_white',
    xaxis: { type: 'date', tickformat: '%d %b', tickangle: 0 },
    yaxis: { title: 'Pedidos' },
    hovermode: 'x unified',
    margin: { t: 20, b: 60, l: 60, r: 20 },
  });
}

function renderKpisVariacion(containerId, kpisData) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';

  const fmtPct = (v) => {
    if (v == null) return '—';
    const sign = v >= 0 ? '+' : '';
    return `${sign}${v.toFixed(1)}%`;
  };
  const fmtNum = (v) => Number(v).toLocaleString('es-MX');

  // Card de total
  const totalCard = document.createElement('div');
  totalCard.className = 'kpi-card';
  const totalClass = kpisData.total_variacion_pct == null ? 'kpi-variacion-flat'
                   : kpisData.total_variacion_pct >= 0 ? 'kpi-variacion-up'
                   : 'kpi-variacion-down';
  totalCard.innerHTML = `
    <span class="kpi-label">Total este mes</span>
    <span class="kpi-value">${fmtNum(kpisData.total_actual)}</span>
    <span class="kpi-sublabel ${totalClass}">
      ${fmtPct(kpisData.total_variacion_pct)} vs mes anterior
    </span>
  `;
  container.appendChild(totalCard);

  // Una card por segmento
  kpisData.por_segmento.forEach(s => {
    const card = document.createElement('div');
    card.className = 'kpi-card';
    const cls = s.variacion_pct == null ? 'kpi-variacion-flat'
              : s.variacion_pct >= 0 ? 'kpi-variacion-up'
              : 'kpi-variacion-down';
    card.innerHTML = `
      <span class="kpi-label">${s.segmento}</span>
      <span class="kpi-value">${fmtNum(s.pedidos_actual)}</span>
      <span class="kpi-sublabel ${cls}">${fmtPct(s.variacion_pct)}</span>
    `;
    container.appendChild(card);
  });
}
```

Exponer en `window.PulseCharts` si es el patrón usado.

### Dispatcher en el template

Al final de `estacionalidad.html`, dentro del `<script>` de inicialización:

```javascript
const initial = JSON.parse(document.getElementById('initial-data').textContent);

// Render inicial (modo histórico que ya existe)
PulseCharts.renderEvolucionMensual('grafica-evolucion-mensual', initial.historico.mensual);

// Pre-render modo último mes (estará oculto pero listo para el toggle)
PulseCharts.renderKpisVariacion('kpis-variacion', initial.ultimo_mes.kpis);
PulseCharts.renderEvolucionDiaria(
  'grafica-evolucion-diaria',
  initial.ultimo_mes.actual,
  initial.ultimo_mes.anterior,
);

// Toggle
document.querySelectorAll('#f-modo-temporal button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#f-modo-temporal button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const modo = btn.dataset.modo;
    document.getElementById('modo-historico').classList.toggle('hidden', modo !== 'historico');
    document.getElementById('modo-ultimo-mes').classList.toggle('hidden', modo !== 'ultimo-mes');

    // Plotly necesita resize cuando la gráfica pasa de hidden a visible
    const containerId = modo === 'ultimo-mes' ? 'grafica-evolucion-diaria' : 'grafica-evolucion-mensual';
    Plotly.Plots.resize(document.getElementById(containerId));
  });
});
```

---

## Tests

Agregar a `tests/test_temporalidad.py`:

```python
def test_calcular_temp_diario_ventana_correcta():
    """Verifica que solo se incluyen pedidos dentro de la ventana de N días."""
    import pandas as pd
    from pulse.analytics.temporalidad import calcular_temp_diario

    fecha_ref = pd.Timestamp("2026-06-09 12:00:00", tz="UTC")

    df_orders = pd.DataFrame({
        "order_id":   ["a", "b", "c"],
        "cliente_id": ["c1", "c1", "c2"],
        "fecha": pd.to_datetime([
            "2026-06-08 10:00:00+00:00",  # dentro
            "2026-04-01 10:00:00+00:00",  # fuera (>90 días)
            "2026-06-01 10:00:00+00:00",  # dentro
        ], utc=True),
        "pago_total": [1000.0, 500.0, 2000.0],
    })
    df_segmentos = pd.DataFrame({
        "cliente_id":       ["c1", "c2"],
        "segmento_cluster": ["MVPs", "Alto Valor"],
    })

    resultado = calcular_temp_diario(
        df_orders=df_orders,
        df_segmentos=df_segmentos,
        fecha_ref=fecha_ref,
        dias_atras=90,
    )

    assert len(resultado) == 2  # solo 'a' y 'c'
    assert set(resultado["segmento"].unique()) == {"MVPs", "Alto Valor"}


def test_calcular_temp_diario_vacio_si_no_hay_pedidos():
    """Si no hay pedidos en la ventana, devuelve DataFrame vacío con columnas correctas."""
    import pandas as pd
    from pulse.analytics.temporalidad import calcular_temp_diario

    df_orders = pd.DataFrame(columns=["order_id", "cliente_id", "fecha", "pago_total"])
    df_orders["fecha"] = pd.to_datetime(df_orders["fecha"], utc=True)

    df_segmentos = pd.DataFrame(columns=["cliente_id", "segmento_cluster"])

    resultado = calcular_temp_diario(df_orders, df_segmentos)
    assert resultado.empty
    assert set(resultado.columns) == {"fecha_dia", "segmento", "pedidos", "revenue"}


def test_temp_diario_revenue_no_negativo():
    """En producción, revenue y pedidos siempre deben ser >= 0."""
    from pulse.dashboard.queries import temp_diario_ultimo_mes

    rows = temp_diario_ultimo_mes()
    for r in rows:
        assert r["revenue"] >= 0
        assert r["pedidos"] >= 0
```

---

## Verificación post-implementación

### Manual

1. `uv run python -m pulse.pipeline weekly` (regenera todos los parquets incluido `temp_diario`).
2. Verificar el parquet:
   ```bash
   uv run python -c "import pandas as pd; df=pd.read_parquet('datos/processed/temp_diario.parquet'); print(df.head(15)); print(f'Total: {len(df)} filas, {df.fecha_dia.nunique()} días, {df.segmento.nunique()} segmentos')"
   ```
3. Abrir `/dashboard/estacionalidad`:
   * Toggle "Histórico mensual" se ve igual que antes.
   * Click en "Último mes" → cambia a vista con KPIs + gráfica diaria.
   * Líneas continuas (mes actual) y punteadas (mes anterior) superpuestas correctamente.
   * KPIs muestran % verde (subida) o rojo (bajada).

### Smoke test

Si hoy es 9 de junio:

* Mes actual: hasta 9 puntos visibles (1 al 9 de junio).
* Mes anterior: 9 puntos (1 al 9 de mayo).
* KPIs comparando los totales acumulados.

---

## Sobre el deploy

Este SPEC toca `src/pulse/analytics/` y `src/pulse/pipeline/`, que están en los `REGEN_TRIGGER_PATHS` de `deploy.sh`. Por lo tanto:

1. Commit + push a `main`.
2. CI corre tests nuevos. Verde.
3. Polling cron detecta cambio en ≤5 min.
4. `deploy.sh`: `git pull` + `uv sync` + **regenera parquets con `weekly`** + restart.
5. Dashboard en producción muestra el nuevo modo.

Es el segundo test real del CI/CD con regeneración automática de parquets.

---

## Definición de "Hecho"

* [ ] `calcular_temp_diario()` implementado en `temporalidad.py`.
* [ ] `runner.py` genera `temp_diario.parquet` en cada corrida.
* [ ] `validacion.py` tiene quality check de `temp_diario`.
* [ ] `db.py` registra la vista DuckDB de `temp_diario`.
* [ ] 3 funciones nuevas en `queries.py`.
* [ ] Endpoint `/api/estacionalidad/ultimo-mes` responde 200.
* [ ] Handler de página pre-carga ambos modos.
* [ ] Template `estacionalidad.html` con toggle y dos modos.
* [ ] `charts.js` con `renderEvolucionDiaria` y `renderKpisVariacion`.
* [ ] Tests nuevos pasan localmente.
* [ ] Verificación manual: toggle funciona, KPIs correctos, gráfica diaria superpone ambos meses.
* [ ] CI verde después del push.
* [ ] Deploy automático regenera parquets correctamente.
* [ ] Verificación en producción.

---

## Lo que NO está en este SPEC

* **Comparación contra el mismo mes del año anterior** (junio 2026 vs junio 2025). Otro SPEC si se necesita.
* **Forecasting** del cierre de mes. Fase 5+.
* **Alertas automáticas** cuando la variación es extrema. Sin alcance ahora.
* **Filtros adicionales** dentro del modo "Último mes". Si marketing lo pide, otra iteración.

---

## Orden de implementación sugerido

1. **Pipeline analítico** : `temporalidad.py` + `runner.py` + `validacion.py`. Tests unitarios primero.
2. **Regenerar parquets localmente** : `uv run python -m pulse.pipeline weekly`. Verificar que `temp_diario.parquet` se crea.
3. **Backend del dashboard** : `db.py` + `queries.py` + `api.py` + `pages.py`. Probar endpoints con curl.
4. **Frontend** : template + CSS + JS. Verificación visual local.
5. **Tests nuevos** y verificar que todos pasan.
6. **Commit + push** a feature branch.
7. **CI verde** + merge a main.
8. **Observar polling automático** y verificar en producción.
