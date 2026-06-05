
# SPEC: Corregir queries downstream para usar moneda normalizada

**Versión:** 1.0
**Autor:** Angel Merino
**Fecha:** Junio 2026
**Estado:** Listo para implementación
**Tamaño:** Quirúrgico — solo cambios en queries, sin tocar pipeline ni datos.

---

## Contexto

Durante una sesión de revisión del dashboard descubrimos que el cliente PAC0751 mostraba:

* KPI `monetary`: **$8,929,504** (correcto)
* Tabla "Top productos del cliente" `revenue_total` para única familia: **$1,060,440** (incorrecto, factor ~8x menor)

Diagnóstico paso a paso:

1. **Las 14 órdenes del cliente tienen sus items completos.** No es problema de órdenes huérfanas.
2. **No es CARGO100.** Los items se filtran bien.
3. **Es moneda mixta.** El 53% de items en la base están en USD (958,274 de 1.77M items totales), pero las queries downstream multiplican `cantidad × precio_final` sin convertir USD a MXN.
4. **Los datos YA están normalizados.** El ETL agrega columnas `precio_mxn` y `subtotal_mxn` vía `enrich_items()` en `etl/transform.py`. Estas columnas están poblados al 100% en el parquet histórico (verificado).
5. **El bug es solo en la capa de consumo.** Las queries en `mba.py` y `dashboard/queries.py` siguen usando `precio_final` y `cantidad * precio_final` (moneda nativa, mixta).

### Cifras del diagnóstico

```
Items por moneda en producción:
  USD:  958,274 items (52.5%)
  MXN:  890,199 items (47.5%)

Verificación de columnas normalizadas:
  precio_mxn poblado:    100% en USD y MXN
  subtotal_mxn poblado:  100% en USD y MXN

TC promedio:  18.46 USD→MXN  (variable por fecha, ya aplicado en parquet)
```

### Decisiones arquitectónicas

**Las queries deben usar `subtotal_mxn`, no recalcular.** La normalización es responsabilidad del ETL, no de cada query. Esto es:

* Más eficiente (no se recalcula en cada query).
* Más correcto (usa el TC histórico real del pedido, no un TC estimado).
* Más mantenible (una sola fuente de verdad).
* Más auditable (`enrich_items` está en un solo lugar).

### Archivos afectados

* `src/pulse/dashboard/queries.py` — funciones que calculan revenue por familia, bundles, etc.
* `src/pulse/analytics/mba.py` — cálculo de `ticket_medio` y `revenue_total` en reglas accionables.
* `src/pulse/dashboard/templates/cliente.html` — renombrar columna y agregar tooltip.
* `tests/test_queries.py` — nuevo test de consistencia.

### Archivos NO afectados

* `src/pulse/etl/*` — los datos ya están bien.
* `src/pulse/analytics/rfm.py` — `monetary` usa `pago_total` de orders, ya en MXN.
* `src/pulse/analytics/segmentacion.py` — no toca dinero.
* `src/pulse/analytics/temporalidad.py` — no calcula revenue, solo cuenta pedidos.
* Parquets en `datos/processed/` — no requieren regeneración.

---

## Cambio 1: `dashboard/queries.py` — todas las queries monetarias

### 1.1 `cliente_productos_top()`

**Antes:**

```python
SELECT
    familia,
    COUNT(DISTINCT order_id)                          AS n_pedidos,
    SUM(cantidad)                                     AS unidades_totales,
    SUM(cantidad * precio_final)                      AS revenue_total,
    MAX(fecha)                                        AS ultima_compra
FROM items
WHERE cliente_id = ?
  AND clave != 'CARGO100'
  AND familia IS NOT NULL
GROUP BY familia
ORDER BY revenue_total DESC
LIMIT ?
```

**Después:**

```python
SELECT
    familia,
    COUNT(DISTINCT order_id)                          AS n_pedidos,
    SUM(cantidad)                                     AS unidades_totales,
    SUM(subtotal_mxn)                                 AS revenue_total,
    MAX(fecha)                                        AS ultima_compra
FROM items
WHERE cliente_id = ?
  AND clave != 'CARGO100'
  AND familia IS NOT NULL
GROUP BY familia
ORDER BY revenue_total DESC
LIMIT ?
```

### 1.2 Auditar TODAS las queries del archivo

Buscar en `queries.py` cualquier ocurrencia de:

* `cantidad * precio_final`
* `cantidad*precio_final`
* `SUM(precio_final)` (en contextos monetarios)

Y reemplazar por `subtotal_mxn` o `SUM(subtotal_mxn)` según corresponda.

> [!IMPORTANT]
> Antes de hacer reemplazo global, **buscar con grep/ripgrep** todas las ocurrencias y revisar caso por caso. Puede haber lugares donde `precio_final` se use con intención (mostrar el precio nativo) y no quieras reemplazarlo.

Comando útil:

```bash
rg "precio_final|cantidad\s*\*\s*precio" src/pulse/
```

---

## Cambio 2: `analytics/mba.py` — ticket_medio y revenue_total

En la función que calcula métricas monetarias para reglas accionables (probablemente `_calcular_metricas_monetarias` o similar), reemplazar:

**Antes:**

```python
# Para cada regla accionable: ticket promedio y revenue total
df_metricas = df_pedidos_que_cumplen.groupby("regla_id").agg(
    ticket_medio=("cantidad * precio_final", "mean"),  # o equivalente
    revenue_total=("cantidad * precio_final", "sum"),
)
```

**Después:**

```python
df_metricas = df_pedidos_que_cumplen.groupby("regla_id").agg(
    ticket_medio=("subtotal_mxn", "mean"),
    revenue_total=("subtotal_mxn", "sum"),
)
```

> [!NOTE]
> El nombre exacto de la función y la estructura del groupby pueden variar — el principio es: cualquier suma o promedio monetario debe consumir `subtotal_mxn` directamente.

Si la función necesita el precio unitario por algún motivo, usar `precio_mxn` en lugar de `precio_final`.

---

## Cambio 3: `templates/cliente.html` — UX

### 3.1 Renombrar columna

En la sección "Top productos del cliente":

**Antes:**

```html
<th>Revenue total</th>
```

**Después:**

```html
<th title="Revenue total en MXN. Para items facturados en USD, se aplicó el tipo de cambio del día del pedido (TC histórico). La suma de esta columna refleja el valor real pagado por el cliente.">Revenue (MXN)</th>
```

### 3.2 Actualizar texto bajo el título de la sección

**Antes:**

```html
<p class="subtitle" id="prod-summary">—</p>
```

(generado dinámicamente en JS con "N familias compradas")

**Después:** mantener el JS que genera el resumen, pero asegurar que el tooltip de la columna explica la conversión.

### 3.3 Mismo tratamiento en Bundles y MBA

Si la tabla de "Bundles que el cliente compra juntos" o la tabla principal de Bundles muestran `ticket_medio` o `revenue_total`, agregar tooltip equivalente:

```html
<th title="Revenue en MXN. Items facturados en USD están convertidos con el tipo de cambio histórico del pedido.">Revenue total</th>
<th title="Ticket promedio del bundle en MXN (TC histórico aplicado a items USD).">Ticket medio</th>
```

---

## Cambio 4: Tests de consistencia

Agregar a `tests/test_queries.py`:

```python
def test_revenue_total_suma_a_monetary():
    """La suma de revenue_total de TODAS las familias de un cliente debe
    coincidir con su monetary RFM (dentro de un margen de redondeo).

    Si no coincide, hay un bug de moneda o un filtro inconsistente entre
    items y orders.
    """
    from pulse.dashboard.queries import cliente_productos_top, cliente_perfil

    # Cliente de prueba con compras en USD (caso problemático histórico)
    cliente_id = "PAC0751"
    productos = cliente_productos_top(cliente_id, limit=999)  # sin límite efectivo
    perfil = cliente_perfil(cliente_id)

    suma_revenue = sum(p["revenue_total"] for p in productos)
    monetary = perfil["monetary"]

    # Tolerancia: 5% por diferencias legítimas entre pago_total (incluye IVA,
    # cargos extra) y subtotal_mxn (solo productos). Si la diferencia es mayor,
    # algo está mal estructuralmente.
    diferencia_pct = abs(suma_revenue - monetary) / monetary
    assert diferencia_pct < 0.05, (
        f"Suma de revenue ({suma_revenue:,.0f}) no coincide con monetary "
        f"({monetary:,.0f}). Diferencia: {diferencia_pct:.1%}"
    )


def test_revenue_total_no_es_subestimado_para_usd():
    """Verificación específica: clientes con catálogo principalmente USD
    deben mostrar revenue en órdenes de magnitud razonables vs su monetary.

    Antes del fix, PAC0751 mostraba $1.06M en revenue cuando su monetary
    real era $8.93M (factor ~8x por no convertir USD).
    """
    from pulse.dashboard.queries import cliente_productos_top, cliente_perfil

    cliente_id = "PAC0751"
    productos = cliente_productos_top(cliente_id, limit=999)
    perfil = cliente_perfil(cliente_id)

    suma_revenue = sum(p["revenue_total"] for p in productos)
    monetary = perfil["monetary"]

    # Después del fix, la suma de revenue debe ser al menos el 50% del
    # monetary (sería 100% si no hubiera IVA ni cargos extra).
    assert suma_revenue / monetary > 0.5, (
        f"Revenue ({suma_revenue:,.0f}) es menos del 50% del monetary "
        f"({monetary:,.0f}). Probablemente las queries siguen usando "
        f"precio_final sin normalizar."
    )
```

> [!NOTE]
> Estos dos tests requieren parquets reales. Si en el CI los tests del dashboard están skippeados (como decidimos en la sesión anterior), estos tests también se saltarán. Eso es OK — el test corre en local cuando hagas `uv run pytest` y se ejecuta en producción cuando regeneres los parquets.

---

## Verificación post-implementación

### Manual: PAC0751

```bash
# En el servidor o local
cd /home/angel.merino/ct-analytics
uv run python << 'EOF'
from pulse.dashboard.queries import cliente_productos_top, cliente_perfil

productos = cliente_productos_top("PAC0751", limit=10)
perfil = cliente_perfil("PAC0751")

print(f"Monetary RFM: ${perfil['monetary']:,.0f}")
print(f"Suma revenue (top 10): ${sum(p['revenue_total'] for p in productos):,.0f}")
print(f"\nDetalle:")
for p in productos:
    print(f"  {p['familia']:8s}: ${p['revenue_total']:,.0f} ({p['n_pedidos']} pedidos)")
EOF
```

Resultado esperado:

```
Monetary RFM: $8,929,504
Suma revenue (top 10): $X,XXX,XXX  ← debe ser cercano a monetary (>50%)

Detalle:
  ESDMSF  : $8,XXX,XXX  ← antes del fix era $1,060,440
```

### Verificación del bundles dashboard

Abrir `/dashboard/bundles` y verificar que `ticket_medio` y `revenue_total` muestren cifras en órdenes de magnitud razonables. Antes del fix los items USD estaban subestimados ~18x; después deben aparecer correctos.

---

## Sobre el deploy

Este SPEC **no requiere regenerar parquets** porque las columnas necesarias (`precio_mxn`, `subtotal_mxn`) ya existen en `items_historicos.parquet`.

El cambio toca solo `queries.py`, `mba.py` y `cliente.html`. Ninguno de esos paths está en los `REGEN_TRIGGER_PATHS` de `deploy.sh`. Por lo tanto:

1. Commit + push a `main`.
2. El polling cron detecta los cambios en ~5 minutos.
3. `deploy.sh` corre, ve que **NO** son archivos críticos del pipeline, hace `git pull` + `systemctl restart`.
4. Dashboard actualizado en producción sin regenerar nada.

Excepción: si Claude Code modifica `mba.py` (`src/pulse/analytics/`), eso SÍ está en `REGEN_TRIGGER_PATHS` y disparará una regeneración del pipeline (~45-90s). Esto es deseable porque `mba_accionables.parquet` también necesita los `ticket_medio` y `revenue_total` correctos.

**Será el primer test real del CI/CD end-to-end.** Validamos:

* CI corre tests automáticamente.
* Polling detecta el cambio.
* `deploy.sh` regenera parquets cuando toca `analytics/`.
* Dashboard se actualiza solo.

---

## Definición de "Hecho"

* [ ] `cliente_productos_top()` usa `SUM(subtotal_mxn)` en lugar de `SUM(cantidad * precio_final)`.
* [ ] `mba.py` usa `subtotal_mxn` para cálculos de `ticket_medio` y `revenue_total`.
* [ ] Auditoría de `grep` confirma que no quedan referencias a `cantidad * precio_final` en queries monetarias.
* [ ] `cliente.html` tiene la columna renombrada y tooltip explicativo.
* [ ] Tests nuevos pasan localmente (`uv run pytest tests/test_queries.py -v`).
* [ ] Verificación manual de PAC0751: revenue_total ≈ monetary (margen <5%).
* [ ] CI verde después del push.
* [ ] Polling automático detecta el cambio y regenera parquets (revisar logs de `deploy_*.log` en el servidor).
* [ ] Dashboard en producción muestra cifras correctas.

---

## Lo que NO está en este SPEC

* **Regenerar parquets manualmente** : el polling lo hará automáticamente porque `mba.py` está en los paths críticos.
* **Backfill de datos** : las columnas ya existen, no hay que re-extraer nada de MongoDB.
* **Cambios al ETL** : `enrich_items()` ya está bien implementado.
* **Tests para `mba.py`** : si ya hay tests existentes que validan ticket_medio o revenue_total, deben pasar después del fix; si no hay, no es prioridad agregarlos ahora.
* **Documentación en el portfolio público** : vale agregar una nota en `2_exploracion_datos.qmd` o `7_productizacion.qmd` sobre este bug y su lección, pero como tarea aparte después de validar el fix.

---

## Orden de implementación sugerido

1. **Hacer grep exhaustivo** de `precio_final` y `cantidad * precio_final` en `src/pulse/`. Listar todos los lugares que requieren cambio.
2. **Modificar `queries.py`** (todas las queries monetarias).
3. **Modificar `mba.py`** (cálculos de revenue y ticket).
4. **Actualizar `cliente.html`** (rename + tooltip).
5. **Agregar tests** de consistencia.
6. **Probar localmente** con `uv run pytest` + verificación manual de PAC0751.
7. **Commit + push** a feature branch.
8. **Abrir PR** , esperar CI verde.
9. **Merge a main** .
10. **Observar polling** : en ~5 min, ver el log de `deploy_*.log` en el servidor.
11. **Verificar producción** : abrir dashboard, validar que PAC0751 ahora muestra revenue cercano a monetary.
