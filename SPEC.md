# SPEC: CI con GitHub Actions + CD por polling en servidor

**Versión:** 1.0
**Autor:** Angel Merino
**Fecha:** Junio 2026
**Estado:** Listo para implementación

---

## Contexto

Hoy el ciclo de deployment de Pulse es manual:

1. Desarrollador hace push a `main`.
2. Desarrollador entra al servidor por SSH.
3. `git pull` como `angel.merino`.
4. (A veces se olvida) `uv run python -m pulse.pipeline weekly` para regenerar parquets si hubo cambio de schema.
5. `sudo systemctl restart pulse-dashboard`.

Este flujo tiene tres problemas: **propenso a olvidos** (el paso 4 ya nos rompió producción una vez); **fricción** (entrar manualmente al servidor cada vez); **no hay validación** (código puede llegar a `main` sin tests pasados).

Este SPEC implementa CI/CD en dos partes:

* **CI** : GitHub Actions corre tests + linter en cada push/PR. Si los tests fallan, no se mergea a `main`.
* **CD** : Un cron en el servidor cada 5 minutos verifica si hay nuevos commits en `main`. Si los hay, hace `git pull`, regenera parquets cuando es necesario y reinicia el dashboard.

### Archivos involucrados

* `.github/workflows/ci.yml` — nuevo, define el workflow de CI.
* `deploy.sh` — nuevo, script de deployment que vive en la raíz del repo.
* `crontab` del usuario `angel.merino` — agregar línea del polling.
* `/etc/sudoers.d/pulse-deploy` — nuevo, permite a `angel.merino` reiniciar el servicio sin password.

### Decisiones tomadas explícitamente

* **Branch que se deploya:** `main`.
* **Frecuencia de polling:** cada 5 minutos.
* **Regeneración de parquets:** detectada por cambios en `src/pulse/analytics/`, `src/pulse/modeling/`, o `src/pulse/pipeline/`. En caso de duda, regenerar (better safe than sorry).
* **Lock para evitar deploys concurrentes:** archivo `/tmp/pulse-deploy.lock` con PID.
* **Logging:** cada deploy genera un log en `logs/deploy_YYYYMMDD_HHMMSS.log` en el repo.
* **Notificaciones:** ninguna en v1. Los logs sirven como auditoría.
* **Rollback automático:** ninguno. Si algo falla en producción, se arregla manualmente.
* **Tests requeridos para merge a main:** sí (branch protection rule en GitHub).

---

## Parte 1: CI con GitHub Actions

### 1.1 Archivo `.github/workflows/ci.yml`

Crear el archivo con este contenido:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    name: Tests y linter
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python 3.13
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: "0.4.x"

      - name: Sync dependencies
        run: uv sync --frozen

      - name: Lint with ruff
        run: uv run ruff check . --output-format=github
        continue-on-error: true

      - name: Run tests
        run: uv run pytest -v --tb=short
        env:
          PYTHONPATH: src
```

### 1.2 Configurar branch protection en GitHub

En la UI de GitHub:

1. Ir a  **Settings → Branches → Add rule** .
2. **Branch name pattern:** `main`.
3. Activar:
   * ☑ Require a pull request before merging.
   * ☑ Require status checks to pass before merging.
   * En el buscador de status checks, agregar **`Tests y linter`** (debe aparecer después de la primera corrida del workflow).
   * ☑ Do not allow bypassing the above settings (opcional pero recomendado).
4. Save changes.

> [!NOTE]
> Para que la regla "require status checks" aparezca el check `Tests y linter`, primero el workflow tiene que haber corrido  **al menos una vez** . La primera vez, haces push, esperas a que termine el CI, después configuras la regla.

### 1.3 Asegurar que `pyproject.toml` tiene `ruff` configurado

Si no está configurado, agregar al `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "UP",  # pyupgrade
]
ignore = [
    "E501",  # line too long (formateo manual)
]
```

Y agregar `ruff` como dev dependency:

```bash
uv add --dev ruff
```

> [!IMPORTANT]
> En el workflow CI usamos `continue-on-error: true` para ruff. Esto significa que el linter  **reporta problemas pero no rompe el build** . Es deliberado para no bloquear merges por formato durante la adopción. Cuando el código esté limpio, se puede quitar el `continue-on-error` para hacer el linter obligatorio.

---

## Parte 2: Script `deploy.sh`

### 2.1 Archivo en la raíz del repo

Crear `deploy.sh` con este contenido:

```bash
#!/bin/bash
# deploy.sh — Script de deployment de Pulse
#
# Comportamiento:
# - Si no hay commits nuevos en origin/main, sale sin hacer nada.
# - Si hay commits nuevos, hace pull, regenera parquets si es necesario, y reinicia el dashboard.
# - Logs en logs/deploy_YYYYMMDD_HHMMSS.log
#
# Uso:
#   ./deploy.sh           # corrida normal
#   ./deploy.sh --force   # forzar regeneración aunque no haya cambios
#
# Requiere:
# - Usuario angel.merino con permisos sudo limitados (ver /etc/sudoers.d/pulse-deploy)
# - Variable PULSE_REPO con la ruta al repo (default: directorio del script)

set -e  # salir al primer error

# ─────────────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────────────
PULSE_REPO="${PULSE_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
LOCK_FILE="/tmp/pulse-deploy.lock"
LOG_DIR="${PULSE_REPO}/logs"
LOG_FILE="${LOG_DIR}/deploy_$(date +%Y%m%d_%H%M%S).log"

# Paths que disparan regeneración de parquets
# (cambios fuera de estos solo requieren restart)
REGEN_TRIGGER_PATHS=(
  "src/pulse/analytics/"
  "src/pulse/modeling/"
  "src/pulse/pipeline/"
  "src/pulse/etl/"
  "src/pulse/config/paths.py"
)

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

cleanup() {
  if [ -f "$LOCK_FILE" ] && [ "$(cat "$LOCK_FILE")" = "$$" ]; then
    rm -f "$LOCK_FILE"
  fi
}

trap cleanup EXIT

# ─────────────────────────────────────────────────────────────
# Verificar lock
# ─────────────────────────────────────────────────────────────
if [ -f "$LOCK_FILE" ]; then
  EXISTING_PID=$(cat "$LOCK_FILE")
  if kill -0 "$EXISTING_PID" 2>/dev/null; then
    log "⚠️  Otro deploy en progreso (PID $EXISTING_PID). Saliendo."
    exit 0
  else
    log "🧹 Lock de proceso muerto encontrado. Limpiando."
    rm -f "$LOCK_FILE"
  fi
fi
echo $$ > "$LOCK_FILE"

# ─────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
cd "$PULSE_REPO"

log "🚀 Iniciando deploy desde $PULSE_REPO"

# ─────────────────────────────────────────────────────────────
# Verificar si hay cambios en origin/main
# ─────────────────────────────────────────────────────────────
log "📡 Fetching origin/main..."
git fetch origin main 2>&1 | tee -a "$LOG_FILE"

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse origin/main)

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ] && [ "$1" != "--force" ]; then
  log "✅ Ya en el último commit ($LOCAL_HASH). Nada que hacer."
  rm -f "$LOG_FILE"  # No dejar logs vacíos cuando no hay deploy
  exit 0
fi

log "📥 Hay cambios nuevos."
log "   Local:  $LOCAL_HASH"
log "   Remoto: $REMOTE_HASH"

# ─────────────────────────────────────────────────────────────
# Detectar si necesitamos regenerar parquets
# ─────────────────────────────────────────────────────────────
NEEDS_REGEN=false
CHANGED_FILES=$(git diff --name-only "$LOCAL_HASH" "$REMOTE_HASH")

log "📋 Archivos cambiados:"
echo "$CHANGED_FILES" | tee -a "$LOG_FILE"

for path_pattern in "${REGEN_TRIGGER_PATHS[@]}"; do
  if echo "$CHANGED_FILES" | grep -q "^${path_pattern}"; then
    NEEDS_REGEN=true
    log "🔄 Cambio detectado en '$path_pattern' — se requiere regeneración de parquets."
    break
  fi
done

if [ "$1" = "--force" ]; then
  NEEDS_REGEN=true
  log "🔧 Flag --force detectado: forzando regeneración."
fi

# ─────────────────────────────────────────────────────────────
# Pull
# ─────────────────────────────────────────────────────────────
log "⬇️  git pull..."
git pull origin main 2>&1 | tee -a "$LOG_FILE"

# ─────────────────────────────────────────────────────────────
# Sync dependencies
# ─────────────────────────────────────────────────────────────
log "📦 uv sync..."
uv sync 2>&1 | tee -a "$LOG_FILE"

# ─────────────────────────────────────────────────────────────
# Regenerar parquets si es necesario
# ─────────────────────────────────────────────────────────────
if [ "$NEEDS_REGEN" = true ]; then
  log "🏗️  Regenerando parquets con pipeline weekly..."
  if uv run python -m pulse.pipeline weekly --log-file "$LOG_FILE.pipeline" 2>&1 | tee -a "$LOG_FILE"; then
    log "✅ Pipeline OK."
  else
    log "❌ Pipeline falló. Dashboard NO reiniciado para evitar romperlo."
    log "   Revisa $LOG_FILE.pipeline para detalles."
    exit 1
  fi
else
  log "⏭️  Sin cambios que requieran regenerar parquets."
fi

# ─────────────────────────────────────────────────────────────
# Reiniciar dashboard
# ─────────────────────────────────────────────────────────────
log "🔁 Reiniciando dashboard..."
sudo systemctl restart pulse-dashboard 2>&1 | tee -a "$LOG_FILE"

# Esperar 5 segundos y verificar
sleep 5
if sudo systemctl is-active --quiet pulse-dashboard; then
  log "✅ Dashboard activo."
else
  log "❌ Dashboard NO está activo después del restart. Revisar:"
  log "   sudo systemctl status pulse-dashboard"
  log "   sudo journalctl -u pulse-dashboard -n 50"
  exit 1
fi

NEW_HASH=$(git rev-parse HEAD)
log "🎉 Deploy completado. Ahora en commit $NEW_HASH."
```

Hacer ejecutable:

```bash
chmod +x deploy.sh
```

### 2.2 Reglas importantes del script

* **Idempotente** : corres dos veces seguidas sin cambios, el segundo no hace nada.
* **Lock seguro** : usa PID en archivo. Si el proceso anterior murió sin limpiar, se detecta y se limpia automáticamente.
* **Logs solo cuando hay deploy real** : si no hay cambios, no deja archivos vacíos.
* **Si pipeline falla, NO reinicia el dashboard** : la versión vieja sigue corriendo. Better degraded service than broken service.
* **`set -e` al inicio** : cualquier error intermedio detiene el script.

### 2.3 Pruebas manuales antes de automatizar

Antes de meter el cron, prueba el script en tres escenarios:

**Escenario A: sin cambios**

```bash
./deploy.sh
```

Esperado: "Ya en el último commit. Nada que hacer." Sin tocar nada.

**Escenario B: con cambios cosméticos** (ej. modificar un template HTML)

Hacer commit cosmético, push:

```bash
./deploy.sh
```

Esperado: detecta cambio, hace pull, NO regenera parquets, reinicia dashboard.

**Escenario C: con cambios de schema** (ej. modificar `src/pulse/analytics/segmentacion.py`)

Esperado: detecta cambio en path crítico, hace pull,  **SÍ regenera parquets** , reinicia dashboard.

**Escenario D: forzar regeneración**

```bash
./deploy.sh --force
```

Esperado: regenera parquets aunque no haya cambios.

---

## Parte 3: Sudoers sin password

### 3.1 Configurar

Como root:

```bash
sudo visudo -f /etc/sudoers.d/pulse-deploy
```

Pegar este contenido:

```sudoers
# Permitir a angel.merino reiniciar y consultar el servicio de Pulse sin password.
# Cualquier otra acción con sudo sigue requiriendo password.
angel.merino ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart pulse-dashboard
angel.merino ALL=(ALL) NOPASSWD: /usr/bin/systemctl status pulse-dashboard
angel.merino ALL=(ALL) NOPASSWD: /usr/bin/systemctl is-active pulse-dashboard
```

Guardar. `visudo` valida la sintaxis automáticamente antes de salvar; si hay error te lo dice.

### 3.2 Verificar

Como `angel.merino`:

```bash
sudo systemctl restart pulse-dashboard
# NO debe pedir password
```

Si pide password, hay un error en sudoers. Revisar `/etc/sudoers.d/pulse-deploy` con sintaxis exacta.

### 3.3 Seguridad

Estos permisos son  **scoped** :

* Solo `angel.merino` (no todos los usuarios).
* Solo `systemctl restart`, `status`, `is-active` (no stop, start, enable, disable, ni cualquier otro comando).
* Solo `pulse-dashboard` (no otros servicios).

Cualquier otro `sudo` que `angel.merino` intente correr sigue pidiendo password.

---

## Parte 4: Cron del polling

### 4.1 Agregar al crontab de `angel.merino`

Como `angel.merino` (NO root):

```bash
crontab -e
```

Agregar al final, manteniendo los crons existentes:

```cron
# Pipeline diario (ya existente)
0 3 * * * cd /home/angel.merino/ct-analytics && /home/angel.merino/.local/bin/uv run python -m pulse.pipeline daily --log-file logs/cron_$(date +\%Y\%m\%d).log 2>&1

# Snapshot mensual (ya existente)
0 4 1 * * cd /home/angel.merino/ct-analytics && /home/angel.merino/.local/bin/uv run python -m pulse.pipeline monthly --log-file logs/snapshot_$(date +\%Y\%m).log 2>&1

# NUEVO: polling de deployment cada 5 minutos
*/5 * * * * /home/angel.merino/ct-analytics/deploy.sh >> /home/angel.merino/ct-analytics/logs/cron_deploy.log 2>&1
```

Verificar:

```bash
crontab -l
```

Debe mostrar las tres líneas.

### 4.2 Por qué `*/5` y no cada minuto

Cada 5 minutos:

* Latencia aceptable entre push y deploy (peor caso: 5 min).
* Bajo overhead: `git fetch` sin cambios tarda 1-2 segundos.
* Reduce ruido en logs.

### 4.3 Monitoreo del cron de deploy

El log de cron va a `logs/cron_deploy.log` (acumulativo, sin rotación). Para inspeccionar:

```bash
# Ver actividad reciente
tail -50 /home/angel.merino/ct-analytics/logs/cron_deploy.log

# Ver deploys completos (los individuales con timestamp)
ls -lt /home/angel.merino/ct-analytics/logs/deploy_*.log | head -10

# Ver el último deploy con detalle
ls -lt /home/angel.merino/ct-analytics/logs/deploy_*.log | head -1 | awk '{print $NF}' | xargs cat
```

> [!TIP]
> Si `cron_deploy.log` crece demasiado, agregar un logrotate config. No urgente — un `git fetch` sin cambios escribe ~3 líneas cada 5 minutos = ~864 líneas/día. Aceptable por meses.

---

## Parte 5: Cambios de schema — el caso especial

### 5.1 El problema

Cuando un commit cambia el schema de los parquets (nuevas columnas, nuevos modos del pipeline), el dashboard puede crashear si:

1. `git pull` trae el código nuevo.
2. Regeneración de parquets falla por alguna razón.
3. `set -e` detiene el script ANTES del restart del dashboard.

**Esto es deliberado.** El dashboard sigue corriendo con el código y parquets viejos hasta que la regeneración termine OK. Better degraded service than broken service.

### 5.2 ¿Y si la regeneración falla por una razón legítima?

Por ejemplo: cambias el código del pipeline para incluir una columna nueva, pero el código tiene un bug. La regeneración falla.

 **Comportamiento esperado** :

* `deploy.sh` falla con exit 1, log lo registra.
* Dashboard sigue corriendo con código viejo y parquets viejos.
* En 5 minutos, el siguiente polling reintenta. Si arreglaste el bug y pusheaste, el deploy nuevo funciona. Si no, sigue fallando.

Esto es el sistema funcionando como se espera. No es bug.

### 5.3 Diagnóstico cuando algo no funciona

Si después de un push notas que el dashboard no refleja los cambios:

```bash
# 1. Ver el último intento de deploy
ls -lt logs/deploy_*.log | head -1

# 2. Si NO hay deploy reciente: el cron no está corriendo
crontab -l   # ¿está la línea de */5?
ls -lt logs/cron_deploy.log

# 3. Si SÍ hay deploy reciente pero falló: leer el log
cat logs/deploy_<fecha>.log

# 4. Si el deploy fue OK pero dashboard no cambió: caché del navegador
# Hard refresh: Ctrl+Shift+R
```

---

## Testing

### Tests automáticos (CI)

Una vez que el workflow esté activo, cada push debe correr `pytest` automáticamente. Verifica:

1. Hacer un push trivial (cambio en README, por ejemplo).
2. Ir a la pestaña "Actions" del repo en GitHub.
3. Verificar que el workflow corre y termina en verde.

### Tests manuales del deploy script

Antes de habilitar el cron, correr `./deploy.sh` manualmente en los 4 escenarios de la sección 2.3.

### Test end-to-end

1. Hacer un cambio cosmético en un template (ej. cambiar un texto).
2. Push a `main`.
3. Esperar a que CI termine (verde).
4. Esperar máximo 5 minutos.
5. Verificar `logs/cron_deploy.log` que se ejecutó el deploy.
6. Hard refresh del dashboard, ver el cambio reflejado.

---

## Definición de "Hecho"

* [ ] `.github/workflows/ci.yml` creado, primer push verde.
* [ ] Branch protection rule en `main` configurada para requerir CI verde.
* [ ] `pyproject.toml` con `ruff` configurado (si no lo tenía).
* [ ] `deploy.sh` creado, ejecutable, probado en escenarios A-D.
* [ ] `/etc/sudoers.d/pulse-deploy` configurado, `sudo systemctl restart pulse-dashboard` no pide password para `angel.merino`.
* [ ] Cron de polling cada 5 minutos agregado a `crontab` de `angel.merino`.
* [ ] Test end-to-end: push cosmético → CI verde → dashboard actualizado en ≤5min.
* [ ] Test schema change: push con cambio en `src/pulse/analytics/` → parquets regenerados → dashboard actualizado.

---

## Lo que NO está en este SPEC

* **Notificaciones de éxito/fallo** (email, Slack, Discord). Versión 2 si lo necesitas.
* **Rollback automático** ante fallo. Versión 2.
* **Deploy via webhook** (push-driven en lugar de pull-driven). Polling es más simple y resuelve el caso.
* **Self-hosted GitHub Actions runners** que pudieran tocar el servidor directamente. No necesario para esta iteración.
* **Logrotate de `cron_deploy.log`** . Se agrega después si crece demasiado.
* **Métricas de deploy** (cuántos deploys, cuánto duran). Después.

---

## Orden de implementación sugerido

1. **Parte 1 (CI)** primero. Sin tocar servidor. Validas que el workflow funcione y branch protection esté activa. Pasos 1.1, 1.2, 1.3.
2. **Parte 3 (sudoers)** . Necesario para que `deploy.sh` pueda restartear.
3. **Parte 2 (`deploy.sh`)** . Pruebas manuales antes del cron.
4. **Parte 4 (cron)** . Activar el polling cada 5 min.
5. **Test end-to-end** y observar primer deploy automático en vivo.

> [!IMPORTANT]
> Mientras estés probando `deploy.sh` manualmente en paso 3, **NO actives el cron de polling** todavía. Si hay un bug en el script y se está ejecutando cada 5 minutos, vas a tener cientos de logs basura y posiblemente reinicios innecesarios. Activa el cron solo después de validar el script.
>
