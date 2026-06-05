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

# cron arranca con un PATH mínimo (/usr/bin:/bin) que NO incluye ~/.local/bin,
# donde vive uv. Sin esto, el deploy a mano funciona pero bajo cron falla con
# "uv: command not found" en cuanto hay que correr uv sync / uv run.
export PATH="$HOME/.local/bin:$PATH"

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
