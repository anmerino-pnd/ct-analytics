/* Helpers para construir figuras Plotly con paleta y estilo consistentes. */

window.PulseCharts = (function () {

  const LAYOUT_BASE = {
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
      textinfo: 'label+percent',
      textposition: 'outside',
      hovertemplate: '%{label}<br>%{value:,} clientes<br>%{percent}<extra></extra>',
      sort: false,
    };
    const layout = Object.assign({}, LAYOUT_BASE, {
      showlegend: false,
      margin: { t: 30, r: 20, b: 20, l: 20 },
    }, opts.layout || {});
    Plotly.react(elId, [trace], layout, CONFIG_BASE);
  }

  // ─── Bar: revenue por segmento ──────────────────────────────────
  function renderBarRevenue(elId, data) {
    const ordered = orderSegmentos(data, 'segmento');
    const trace = {
      type: 'bar',
      x: ordered.map(r => r.segmento),
      y: ordered.map(r => r.revenue),
      marker: { color: ordered.map(r => colorOf(r.segmento)) },
      hovertemplate: '%{x}<br>$%{y:,.0f}<extra></extra>',
    };
    const layout = Object.assign({}, LAYOUT_BASE, {
      showlegend: false,
      yaxis: { title: { text: 'Revenue (MXN)' }, tickformat: ',.0f' },
      xaxis: { title: '' },
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
      porSeg[r.segmento].x.push(r.ano_mes);
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
        hovertemplate: '%{x}<br>%{y:,} pedidos<extra>' + s + '</extra>',
      }));
    const layout = Object.assign({}, LAYOUT_BASE, {
      xaxis: { title: 'Año-Mes', type: 'category' },
      yaxis: { title: 'Pedidos', tickformat: ',.0f' },
    });
    Plotly.react(elId, traces, layout, CONFIG_BASE);
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
      xaxis: { title: 'Fecha', type: 'date' },
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
    renderDonut, renderBarRevenue, renderBarBundles,
    renderHeatmapHoraDia, renderLineMensual, renderBarMesCalendario,
    renderScatterCliente, renderClientePedidos, renderScatterAlertas,
    renderRadar, renderBoxMonetary, renderHeatmapBundles,
  };
})();
