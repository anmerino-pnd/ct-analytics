/* Helpers para construir figuras Plotly con paleta y estilo consistentes. */

window.PulseCharts = (function () {

  // Localiza meses/días al español (e.g. tickformat '%b %y' → "jun 24").
  // El locale se carga vía CDN en base.html antes de este script.
  Plotly.setPlotConfig({ locale: 'es' });

  const LAYOUT_BASE = {
    // Tema built-in sin grid de fondo (fondo blanco, ejes con línea fina).
    // Se hereda en cada Object.assign({}, LAYOUT_BASE, {...}). Los heatmaps
    // lo sobreescriben con template:'plotly' (ver renderHeatmap*).
    template: 'simple_white',
    font: { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', size: 13, color: '#1d1d1f' },
    plot_bgcolor: 'white',
    paper_bgcolor: 'white',
    margin: { t: 30, r: 20, b: 50, l: 60 },
    hovermode: 'closest',
    showlegend: true,
  };

  const CONFIG_BASE = {
    displaylogo: false,
    responsive: true,
    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
  };

  function colorOf(segmento) {
    return (window.SEGMENT_COLORS && window.SEGMENT_COLORS[segmento]) || '#888';
  }

  function orderSegmentos(rows, key) {
    const order = window.SEGMENT_ORDER || [];
    return rows.slice().sort(
      (a, b) => order.indexOf(a[key]) - order.indexOf(b[key])
    );
  }

  // Inserta saltos de línea en labels de segmento multi-palabra para que
  // quepan horizontalmente sin solaparse (e.g. "Alto Valor" → "Alto<br>Valor").
  function wrapSegmentLabel(s) {
    return (s || '').replace(/ /g, '<br>');
  }

  // ─── Donut: distribución de clientes ────────────────────────────
  function renderDonut(elId, data, opts = {}) {
    const ordered = orderSegmentos(data, 'segmento');
    const labels = ordered.map(r => r.segmento);
    const values = ordered.map(r => r.n_clientes);
    const colors = labels.map(colorOf);

    const trace = {
      type: 'pie',
      labels, values,
      hole: 0.55,
      marker: { colors, line: { color: 'white', width: 2 } },
      // Solo % en la rebanada (los nombres van en la leyenda → no se solapan)
      textinfo: 'percent',
      textposition: 'inside',
      insidetextorientation: 'horizontal',
      textfont: { color: 'white', size: 13 },
      hovertemplate: '%{label}<br>%{value:,} clientes<br>%{percent}<extra></extra>',
      sort: false,
    };
    const layout = Object.assign({}, LAYOUT_BASE, {
      showlegend: true,
      legend: {
        orientation: 'v',
        x: 1, xanchor: 'left',
        y: 0.5, yanchor: 'middle',
        font: { size: 13 },
        itemsizing: 'constant',
      },
      margin: { t: 20, r: 140, b: 20, l: 20 },
    }, opts.layout || {});
    Plotly.react(elId, [trace], layout, CONFIG_BASE);
  }

  // ─── Bar: revenue por segmento ──────────────────────────────────
  function renderBarRevenue(elId, data) {
    const ordered = orderSegmentos(data, 'segmento');
    const trace = {
      type: 'bar',
      x: ordered.map(r => wrapSegmentLabel(r.segmento)),
      y: ordered.map(r => r.revenue),
      marker: { color: ordered.map(r => colorOf(r.segmento)) },
      // Hover muestra el segmento sin el <br>
      customdata: ordered.map(r => r.segmento),
      hovertemplate: '%{customdata}<br>$%{y:,.0f}<extra></extra>',
    };
    const layout = Object.assign({}, LAYOUT_BASE, {
      showlegend: false,
      yaxis: {
        title: { text: 'Revenue (MXN)' },
        // '$~s' abrevia a $k/$M/$G (e.g. $1.21G) — números compactos
        tickprefix: '$',
        tickformat: '~s',
        separatethousands: true,
      },
      xaxis: { title: '', tickangle: 0, automargin: true },
      margin: { t: 30, r: 20, b: 70, l: 70 },
    });
    Plotly.react(elId, [trace], layout, CONFIG_BASE);
  }

  // ─── Bar horizontal: top N reglas/bundles ───────────────────────
  function renderBarBundles(elId, rules) {
    // rules: [{antecedents, consequents, revenue_total, segmento}]
    const labels = rules.map(r => `${r.antecedents} → ${r.consequents}`);
    const x = rules.map(r => r.revenue_total != null ? r.revenue_total : r.support_count);
    const colors = rules.map(r => colorOf(r.segmento));
    const tieneRev = rules.some(r => r.revenue_total != null);

    const trace = {
      type: 'bar',
      orientation: 'h',
      x, y: labels,
      marker: { color: colors },
      hovertemplate: tieneRev
        ? '%{y}<br>Revenue: $%{x:,.0f}<extra></extra>'
        : '%{y}<br>Support count: %{x:,}<extra></extra>',
    };
    const layout = Object.assign({}, LAYOUT_BASE, {
      showlegend: false,
      margin: { t: 30, r: 20, b: 50, l: 200 },
      xaxis: { title: tieneRev ? 'Revenue (MXN)' : 'Support count', tickformat: ',.0f' },
      yaxis: { autorange: 'reversed' },
      height: Math.max(360, 28 * rules.length + 80),
    });
    Plotly.react(elId, [trace], layout, CONFIG_BASE);
  }

  // ─── Scatter "Market Basket Opportunity Map" ────────────────────
  // Replica v3 del notebook:
  //   x: confidence  |  y: lift  |  tamaño: support  |  color: cuadrante
  // Las líneas divisorias usan la MEDIANA de confidence y lift de las reglas
  // mostradas (recalculado al filtrar). Esto garantiza división balanceada.
  // Hover muestra el segmento de cada regla.
  function renderScatterBundles(elId, rules, opts = {}) {
    if (!rules.length) {
      Plotly.purge(elId);
      return;
    }

    // Cuadrantes basados en la mediana (consistente con v3)
    const sortedConf = rules.map(r => r.confidence).slice().sort((a, b) => a - b);
    const sortedLift = rules.map(r => r.lift).slice().sort((a, b) => a - b);
    const median = arr => {
      const n = arr.length;
      return n % 2 === 0 ? (arr[n/2 - 1] + arr[n/2]) / 2 : arr[(n-1)/2];
    };
    const confMid = median(sortedConf);
    const liftMid = median(sortedLift);

    // Paleta de cuadrantes (de v3)
    const QUADRANT_COLORS = {
      "Oportunidades fuertes":  "#0B3C5D",
      "Co-compras frecuentes":  "#328CC1",
      "Nichos interesantes":    "#D82822",
      "Ruido":                  "#9AA0A6",
    };
    const QUADRANT_ORDER = [
      "Oportunidades fuertes",
      "Co-compras frecuentes",
      "Nichos interesantes",
      "Ruido",
    ];

    // Clasificar cada regla
    function clasificar(r) {
      const altaConf = r.confidence >= confMid;
      const altoLift = r.lift >= liftMid;
      if (altaConf && altoLift)  return "Oportunidades fuertes";
      if (altaConf && !altoLift) return "Co-compras frecuentes";
      if (!altaConf && altoLift) return "Nichos interesantes";
      return "Ruido";
    }
    rules.forEach(r => r._cuadrante = clasificar(r));

    // Escalar tamaño de burbujas
    const supports = rules.map(r => r.support_count || 1);
    const maxSupport = Math.max(...supports, 1);
    const sizeref = 2 * maxSupport / (40 ** 2);

    // Agrupar por cuadrante para que la leyenda muestre los 4 grupos
    const porCuad = {};
    rules.forEach(r => {
      if (!porCuad[r._cuadrante]) porCuad[r._cuadrante] = [];
      porCuad[r._cuadrante].push(r);
    });

    const traces = QUADRANT_ORDER
      .filter(q => porCuad[q])
      .map(q => {
        const sub = porCuad[q];
        return {
          type: 'scatter',
          mode: 'markers',
          name: q + ' (' + sub.length + ')',
          x: sub.map(r => r.confidence),
          y: sub.map(r => r.lift),
          marker: {
            size: sub.map(r => r.support_count || 1),
            sizemode: 'area',
            sizeref: sizeref,
            sizemin: 4,
            color: QUADRANT_COLORS[q],
            opacity: 0.65,
            line: { color: 'white', width: 1 },
          },
          customdata: sub.map(r => [
            r.antecedents,
            r.consequents,
            r.support_count,
            r.revenue_total,
            r.ticket_medio,
            r.segmento,
          ]),
          hovertemplate: (function () {
            // Solo incluimos revenue/ticket si hay datos (vista marketing).
            // En vista exploratoria llegan null y mostrarlos da texto literal feo.
            const tieneValor = sub.some(r => r.revenue_total != null);
            const baseTpl =
              '<b>%{customdata[0]} → %{customdata[1]}</b>' +
              '<br>Segmento: %{customdata[5]}' +
              '<br>Confidence: %{x:.1%}' +
              '<br>Lift: %{y:.2f}' +
              '<br>Support: %{customdata[2]:,} pedidos';
            const valorTpl = tieneValor
              ? '<br>Revenue: $%{customdata[3]:,.0f}' +
                '<br>Ticket medio: $%{customdata[4]:,.0f}'
              : '';
            return baseTpl + valorTpl + '<extra></extra>';
          })(),
        };
      });

    const xMin = Math.min(...rules.map(r => r.confidence)) - 0.02;
    const xMax = Math.max(...rules.map(r => r.confidence)) + 0.02;
    const yMin = 0;
    const yMax = Math.max(...rules.map(r => r.lift)) * 1.05;

    const layout = Object.assign({}, LAYOUT_BASE, {
      xaxis: {
        title: { text: 'Confidence (qué tan seguro es el patrón)' },
        tickformat: '.0%',
        range: [xMin, xMax],
        zeroline: false,
      },
      yaxis: {
        title: { text: 'Lift (qué tan fuerte es la asociación)' },
        range: [yMin, yMax],
        zeroline: false,
      },
      shapes: [
        {
          type: 'line',
          x0: confMid, x1: confMid, y0: yMin, y1: yMax,
          line: { color: '#9AA0A6', width: 1, dash: 'dash' },
        },
        {
          type: 'line',
          x0: xMin, x1: xMax, y0: liftMid, y1: liftMid,
          line: { color: '#9AA0A6', width: 1, dash: 'dash' },
        },
      ],
      annotations: [
        {
          x: confMid, y: yMax, xanchor: 'left', yanchor: 'top',
          text: 'conf=' + (confMid * 100).toFixed(0) + '%',
          showarrow: false,
          font: { size: 10, color: '#666' },
          bgcolor: 'rgba(255,255,255,0.8)',
          xshift: 4,
        },
        {
          x: xMax, y: liftMid, xanchor: 'right', yanchor: 'bottom',
          text: 'lift=' + liftMid.toFixed(1),
          showarrow: false,
          font: { size: 10, color: '#666' },
          bgcolor: 'rgba(255,255,255,0.8)',
          yshift: 4,
        },
      ],
      legend: { title: { text: 'Cuadrante (clic para ocultar/mostrar)' } },
      height: 520,
      margin: { t: 30, r: 20, b: 60, l: 60 },
    });

    Plotly.react(elId, traces, layout, CONFIG_BASE);
  }

  // ─── Heatmap hora × día por segmento ────────────────────────────
  function renderHeatmapHoraDia(elId, rows, segmento) {
    // rows filtradas a UN solo segmento
    const dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];
    const horas = [...Array(24).keys()];
    const z = dias.map((_, d) => horas.map(() => 0));
    rows.forEach(r => {
      const di = r.dia_semana;
      const hi = r.hora;
      if (di >= 0 && di < 7 && hi >= 0 && hi < 24) {
        z[di][hi] = r.pct * 100;
      }
    });
    const trace = {
      type: 'heatmap',
      z, x: horas, y: dias,
      colorscale: [[0, '#f7f7f7'], [1, colorOf(segmento)]],
      hovertemplate: '%{y} %{x}:00<br>%{z:.2f}% del segmento<extra></extra>',
      colorbar: { thickness: 10, len: 0.8, tickformat: '.2f', ticksuffix: '%' },
    };
    const layout = Object.assign({}, LAYOUT_BASE, {
      template: 'plotly',  // heatmap: conserva el template default (excluido del tema global)
      title: { text: segmento, font: { size: 14 } },
      xaxis: { title: 'Hora', dtick: 2, tickfont: { size: 11 } },
      yaxis: { autorange: 'reversed', tickfont: { size: 11 } },
      showlegend: false,
      height: 280,
      margin: { t: 40, r: 20, b: 40, l: 80 },
    });
    Plotly.react(elId, [trace], layout, CONFIG_BASE);
  }

  // ─── Line chart mensual ─────────────────────────────────────────
  function renderLineMensual(elId, rows) {
    const orden = window.SEGMENT_ORDER || [];
    const porSeg = {};
    rows.forEach(r => {
      if (!porSeg[r.segmento]) porSeg[r.segmento] = { x: [], y: [] };
      // ano_mes llega como string "2024-06" → "2024-06-01" para que el eje
      // lo trate como fecha (ticks cada 6 meses, sin etiquetas verticales).
      porSeg[r.segmento].x.push(r.ano_mes + '-01');
      porSeg[r.segmento].y.push(r.pedidos);
    });
    const traces = orden
      .filter(s => porSeg[s])
      .map(s => ({
        type: 'scatter', mode: 'lines+markers',
        name: s,
        x: porSeg[s].x, y: porSeg[s].y,
        line: { color: colorOf(s), width: 2 },
        marker: { size: 5 },
        hovertemplate: '%{x|%b %Y}<br>%{y:,} pedidos<extra>' + s + '</extra>',
      }));
    const layout = Object.assign({}, LAYOUT_BASE, {
      xaxis: { title: '', type: 'date', tickangle: 0, dtick: 'M6', tickformat: '%b %y' },
      yaxis: { title: 'Pedidos', tickformat: ',.0f' },
    });
    Plotly.react(elId, traces, layout, CONFIG_BASE);
  }

  // ─── Line chart diario: mes en curso vs mismo rango del mes anterior ──
  function renderEvolucionDiaria(elId, datosActual, datosAnterior) {
    const orden = window.SEGMENT_ORDER || [];
    // Agrupar una sola vez por segmento (evita re-filtrar los arrays en cada vuelta).
    const porSegActual = {};
    const porSegAnterior = {};
    datosActual.forEach(d => {
      if (!porSegActual[d.segmento]) porSegActual[d.segmento] = [];
      porSegActual[d.segmento].push(d);
    });
    datosAnterior.forEach(d => {
      if (!porSegAnterior[d.segmento]) porSegAnterior[d.segmento] = [];
      porSegAnterior[d.segmento].push(d);
    });
    const segmentos = orden.filter(s => porSegActual[s] || porSegAnterior[s]);

    // Mes en curso (YYYY-MM) para superponer el mes anterior por día-de-mes.
    // Si el mes actual aún no tiene datos, se deriva del mes anterior + 1, de
    // modo que la comparación se ve igual (alineación por número de día, no por
    // índice de arreglo → robusta ante días faltantes y mes actual vacío).
    const addMonthStr = (ym) => {
      let [y, m] = ym.split('-').map(Number);
      m += 1; if (m > 12) { m = 1; y += 1; }
      return y + '-' + String(m).padStart(2, '0');
    };
    const ymActual =
      datosActual.length ? datosActual[0].fecha_dia.slice(0, 7)
      : datosAnterior.length ? addMonthStr(datosAnterior[0].fecha_dia.slice(0, 7))
      : null;

    const traces = [];
    segmentos.forEach(seg => {
      const act = porSegActual[seg] || [];
      traces.push({
        type: 'scatter', mode: 'lines+markers',
        name: seg,
        x: act.map(d => d.fecha_dia),
        y: act.map(d => d.pedidos),
        line: { color: colorOf(seg), width: 2.5 },
        marker: { size: 6 },
        legendgroup: seg,
        hovertemplate: '%{x|%d %b}<br>%{y:,} pedidos<extra>' + seg + ' · este mes</extra>',
      });
      // Mes anterior alineado al mismo día relativo del mes en curso (punteada).
      const ant = porSegAnterior[seg] || [];
      traces.push({
        type: 'scatter', mode: 'lines',
        name: seg + ' (mes anterior)',
        // Superpuesto por día-de-mes sobre el mes en curso (mismo día → misma x).
        x: ymActual ? ant.map(d => ymActual + '-' + d.fecha_dia.slice(8, 10)) : [],
        y: ant.map(d => d.pedidos),
        line: { color: colorOf(seg), width: 1.5, dash: 'dot' },
        legendgroup: seg,
        showlegend: false,
        hovertemplate: '%{x|%d %b}<br>%{y:,} pedidos<extra>' + seg + ' · mes anterior</extra>',
      });
    });
    const layout = Object.assign({}, LAYOUT_BASE, {
      xaxis: { title: '', type: 'date', tickformat: '%d %b', tickangle: 0 },
      yaxis: { title: 'Pedidos', tickformat: ',.0f' },
      hovermode: 'x unified',
      margin: { t: 20, r: 20, b: 60, l: 60 },
    });
    Plotly.react(elId, traces, layout, CONFIG_BASE);
  }

  // ─── KPI cards de variación mensual (mes en curso vs anterior) ──
  function renderKpisVariacion(elId, kpisData) {
    const container = document.getElementById(elId);
    container.innerHTML = '';

    const fmtPct = (v) => {
      if (v == null) return '—';
      const sign = v >= 0 ? '+' : '';
      return sign + v.toFixed(1) + '%';
    };
    const fmtNum = (v) => Number(v).toLocaleString('es-MX');
    const claseVar = (v) => v == null ? 'kpi-variacion-flat'
                          : v >= 0 ? 'kpi-variacion-up'
                          : 'kpi-variacion-down';

    const totalCard = document.createElement('div');
    totalCard.className = 'kpi-card';
    totalCard.innerHTML =
      '<span class="kpi-label">Total este mes</span>' +
      '<span class="kpi-value">' + fmtNum(kpisData.total_actual) + '</span>' +
      '<span class="kpi-sublabel ' + claseVar(kpisData.total_variacion_pct) + '">' +
      fmtPct(kpisData.total_variacion_pct) + ' vs mes anterior</span>';
    container.appendChild(totalCard);

    (kpisData.por_segmento || []).forEach(s => {
      const card = document.createElement('div');
      card.className = 'kpi-card';
      card.innerHTML =
        '<span class="kpi-label">' + s.segmento + '</span>' +
        '<span class="kpi-value">' + fmtNum(s.pedidos_actual) + '</span>' +
        '<span class="kpi-sublabel ' + claseVar(s.variacion_pct) + '">' +
        fmtPct(s.variacion_pct) + '</span>';
      container.appendChild(card);
    });
  }

  // ─── Bar estacionalidad típica (promedio por mes calendario) ────
  function renderBarMesCalendario(elId, rows) {
    const orden = window.SEGMENT_ORDER || [];
    const nombresMes = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
    const porSeg = {};
    rows.forEach(r => {
      if (!porSeg[r.segmento]) porSeg[r.segmento] = { x: [], y: [] };
      porSeg[r.segmento].x.push(nombresMes[r.mes]);
      porSeg[r.segmento].y.push(r.pedidos_promedio);
    });
    const traces = orden
      .filter(s => porSeg[s])
      .map(s => ({
        type: 'bar',
        name: s,
        x: porSeg[s].x, y: porSeg[s].y,
        marker: { color: colorOf(s) },
        hovertemplate: '%{x}<br>%{y:,.0f} pedidos (promedio)<extra>' + s + '</extra>',
      }));
    const layout = Object.assign({}, LAYOUT_BASE, {
      barmode: 'group',
      xaxis: { title: '' },
      yaxis: { title: 'Pedidos promedio por mes', tickformat: ',.0f' },
    });
    Plotly.react(elId, traces, layout, CONFIG_BASE);
  }

  // ─── Scatter: cliente vs su segmento ────────────────────────────
  function renderScatterCliente(elId, rows, segmento) {
    const otros = rows.filter(r => !r.es_objetivo);
    const target = rows.find(r => r.es_objetivo);
    const traces = [
      {
        type: 'scattergl', mode: 'markers',
        name: segmento,
        x: otros.map(r => r.recency), y: otros.map(r => r.monetary),
        marker: { color: '#cccccc', size: 5, opacity: 0.5 },
        hovertemplate: '%{customdata}<br>Recency: %{x}<br>Monetary: $%{y:,.0f}<extra></extra>',
        customdata: otros.map(r => r.cliente_id),
      },
    ];
    if (target) {
      traces.push({
        type: 'scatter', mode: 'markers',
        name: 'Este cliente',
        x: [target.recency], y: [target.monetary],
        marker: { color: colorOf(segmento), size: 16, line: { color: 'black', width: 2 } },
        hovertemplate: target.cliente_id + '<br>Recency: %{x}<br>Monetary: $%{y:,.0f}<extra></extra>',
      });
    }
    const layout = Object.assign({}, LAYOUT_BASE, {
      xaxis: { title: 'Recency (días)' },
      yaxis: { title: 'Monetary (MXN)', type: 'log', tickformat: ',.0f' },
      showlegend: true,
    });
    Plotly.react(elId, traces, layout, CONFIG_BASE);
  }

  // ─── Time series de pedidos del cliente ─────────────────────────
  function renderClientePedidos(elId, pedidos) {
    const trace = {
      type: 'scatter', mode: 'markers+lines',
      x: pedidos.map(p => p.fecha),
      y: pedidos.map(p => p.pago_total),
      marker: { size: 7, color: '#0B3C5D' },
      line: { color: '#0B3C5D', width: 1 },
      hovertemplate: '%{x}<br>$%{y:,.0f}<br>%{customdata} productos<extra></extra>',
      customdata: pedidos.map(p => p.num_productos),
    };
    const layout = Object.assign({}, LAYOUT_BASE, {
      xaxis: { title: '', type: 'date', tickangle: 0, dtick: 'M6', tickformat: '%b %y' },
      yaxis: { title: 'Pago total (MXN)', tickformat: ',.0f' },
      showlegend: false,
    });
    Plotly.react(elId, [trace], layout, CONFIG_BASE);
  }

  // ─── Scatter alertas ────────────────────────────────────────────
  function renderScatterAlertas(elId, rows) {
    const orden = window.SEGMENT_ORDER || [];
    const traces = orden
      .map(s => {
        const sub = rows.filter(r => r.segmento === s);
        if (!sub.length) return null;
        return {
          type: 'scattergl', mode: 'markers',
          name: s,
          x: sub.map(r => r.ratio),
          y: sub.map(r => r.monetary),
          customdata: sub.map(r => r.cliente_id),
          marker: { color: colorOf(s), size: 8, opacity: 0.7 },
          hovertemplate: '%{customdata}<br>Ratio: %{x:.2f}<br>Monetary: $%{y:,.0f}<extra>' + s + '</extra>',
        };
      })
      .filter(t => t !== null);
    const layout = Object.assign({}, LAYOUT_BASE, {
      xaxis: { title: 'Ratio recency / cadencia' },
      yaxis: { title: 'Monetary (MXN)', type: 'log', tickformat: ',.0f' },
    });
    Plotly.react(elId, traces, layout, CONFIG_BASE);
  }

  // ─── Radar comparador ───────────────────────────────────────────
  function renderRadar(elId, ejes, seriesA, seriesB, nombreA, nombreB) {
    const traces = [
      {
        type: 'scatterpolar', fill: 'toself',
        name: nombreA, r: seriesA, theta: ejes,
        line: { color: colorOf(nombreA) },
        marker: { color: colorOf(nombreA) },
      },
      {
        type: 'scatterpolar', fill: 'toself',
        name: nombreB, r: seriesB, theta: ejes,
        line: { color: colorOf(nombreB) },
        marker: { color: colorOf(nombreB) },
      },
    ];
    const layout = Object.assign({}, LAYOUT_BASE, {
      polar: { radialaxis: { visible: true, range: [0, 1] } },
      showlegend: true,
    });
    Plotly.react(elId, traces, layout, CONFIG_BASE);
  }

  // ─── Box plot comparador ────────────────────────────────────────
  function renderBoxMonetary(elId, datosA, nombreA, datosB, nombreB) {
    const traces = [
      {
        type: 'box', name: nombreA, y: datosA,
        marker: { color: colorOf(nombreA) }, boxpoints: false,
      },
      {
        type: 'box', name: nombreB, y: datosB,
        marker: { color: colorOf(nombreB) }, boxpoints: false,
      },
    ];
    const layout = Object.assign({}, LAYOUT_BASE, {
      yaxis: { title: 'Monetary (MXN, log)', type: 'log', tickformat: ',.0f' },
      showlegend: false,
    });
    Plotly.react(elId, traces, layout, CONFIG_BASE);
  }

  // ─── Heatmap bundles × meses ────────────────────────────────────
  function renderHeatmapBundles(elId, rows, segmento) {
    // rows: [{regla, ano_mes, pedidos, revenue}]
    const reglas = [...new Set(rows.map(r => r.regla))];
    const meses  = [...new Set(rows.map(r => r.ano_mes))].sort();
    const idxR = Object.fromEntries(reglas.map((r, i) => [r, i]));
    const idxM = Object.fromEntries(meses.map((m, i) => [m, i]));
    const z = reglas.map(() => meses.map(() => 0));
    const rev = reglas.map(() => meses.map(() => 0));
    rows.forEach(r => {
      z[idxR[r.regla]][idxM[r.ano_mes]] = r.pedidos;
      rev[idxR[r.regla]][idxM[r.ano_mes]] = r.revenue;
    });

    const trace = {
      type: 'heatmap',
      z, x: meses, y: reglas,
      customdata: rev,
      colorscale: [[0, '#f7f7f7'], [1, colorOf(segmento)]],
      hovertemplate: '%{y}<br>%{x}<br>%{z:,} pedidos<br>$%{customdata:,.0f} revenue<extra></extra>',
      colorbar: { thickness: 10, len: 0.8 },
    };
    const layout = Object.assign({}, LAYOUT_BASE, {
      template: 'plotly',  // heatmap: conserva el template default (excluido del tema global)
      xaxis: { title: 'Año-Mes', type: 'category' },
      yaxis: { autorange: 'reversed', automargin: true, tickfont: { size: 11 } },
      margin: { t: 30, r: 20, b: 60, l: 180 },
      height: Math.max(320, 26 * reglas.length + 80),
      showlegend: false,
    });
    Plotly.react(elId, [trace], layout, CONFIG_BASE);
  }

  return {
    LAYOUT_BASE, CONFIG_BASE, colorOf, orderSegmentos,
    renderDonut, renderBarRevenue, renderBarBundles, renderScatterBundles,
    renderHeatmapHoraDia, renderLineMensual, renderBarMesCalendario,
    renderEvolucionDiaria, renderKpisVariacion,
    renderScatterCliente, renderClientePedidos, renderScatterAlertas,
    renderRadar, renderBoxMonetary, renderHeatmapBundles,
  };
})();