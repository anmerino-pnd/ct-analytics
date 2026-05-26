/* Helpers genéricos para filtros y fetch JSON. */

window.PulseFilters = (function () {

  let bannerTimer = null;

  function showError(msg) {
    const banner = document.getElementById('error-banner');
    if (!banner) return;
    if (msg) banner.textContent = msg;
    banner.classList.remove('hidden');
    clearTimeout(bannerTimer);
    bannerTimer = setTimeout(() => banner.classList.add('hidden'), 4000);
  }

  async function fetchJSON(url, opts = {}) {
    try {
      const r = await fetch(url, opts);
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try {
          const body = await r.json();
          if (body.detail) detail = body.detail;
        } catch (_) { /* ignore */ }
        const e = new Error(detail);
        e.status = r.status;
        throw e;
      }
      return await r.json();
    } catch (err) {
      console.error('fetchJSON error', url, err);
      if (!opts.silent) showError('No se pudo cargar los datos. Reintenta.');
      throw err;
    }
  }

  function setLoading(elId, isLoading) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (isLoading) el.classList.add('loading');
    else el.classList.remove('loading');
  }

  // Debounce simple
  function debounce(fn, delay) {
    let t = null;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  return { fetchJSON, showError, setLoading, debounce };
})();
