#!/bin/bash
# setup-sudoers.sh — Configura /etc/sudoers.d/pulse-deploy (Parte 3 del SPEC).
#
# Permite a angel.merino reiniciar/consultar el servicio pulse-dashboard sin
# password. Cualquier otra acción con sudo sigue requiriendo password.
#
# CORRER COMO ROOT en el servidor:
#   sudo bash setup-sudoers.sh
#
# Idempotente: escribe a un temporal, valida con `visudo -c`, y solo si la
# sintaxis es válida instala el archivo final con permisos 0440. Si falla la
# validación, no se toca /etc/sudoers.d/.

set -euo pipefail

SUDOERS_FILE="/etc/sudoers.d/pulse-deploy"
TMP_FILE="$(mktemp)"
DEPLOY_USER="angel.merino"
SYSTEMCTL="/usr/bin/systemctl"
JOURNALCTL="/usr/bin/journalctl"

# Limpiar el temporal pase lo que pase.
trap 'rm -f "$TMP_FILE"' EXIT

# Debe correr como root.
if [ "$(id -u)" -ne 0 ]; then
  echo "❌ Este script debe correr como root. Usa: sudo bash $0" >&2
  exit 1
fi

# Verificar que systemctl está donde esperamos (el SPEC asume /usr/bin/systemctl).
if [ ! -x "$SYSTEMCTL" ]; then
  echo "❌ No existe $SYSTEMCTL (o no es ejecutable)." >&2
  echo "   Verifica con: command -v systemctl" >&2
  echo "   Si la ruta es otra, ajústala en este script antes de continuar." >&2
  exit 1
fi

if [ ! -x "$JOURNALCTL" ]; then
  echo "❌ No existe $JOURNALCTL (o no es ejecutable)." >&2
  exit 1
fi

# Generar el contenido del sudoers.
cat > "$TMP_FILE" <<EOF
# Permitir a ${DEPLOY_USER} reiniciar y consultar el servicio de Pulse sin password.
# Cualquier otra acción con sudo sigue requiriendo password.
# Gestionado por setup-sudoers.sh (Parte 3 del SPEC de CI/CD). No editar a mano.
${DEPLOY_USER} ALL=(ALL) NOPASSWD: ${SYSTEMCTL} restart pulse-dashboard
${DEPLOY_USER} ALL=(ALL) NOPASSWD: ${SYSTEMCTL} status pulse-dashboard
${DEPLOY_USER} ALL=(ALL) NOPASSWD: ${SYSTEMCTL} is-active pulse-dashboard
${DEPLOY_USER} ALL=(ALL) NOPASSWD: ${JOURNALCTL} -u pulse-dashboard *
# deploy.sh llama is-active CON --quiet; sudoers matchea args exactos, así que
# esta variante necesita su propia línea (sin ella, sudo pide password y el
# script truena por set -e en la verificación post-restart).
${DEPLOY_USER} ALL=(ALL) NOPASSWD: ${SYSTEMCTL} is-active --quiet pulse-dashboard
EOF

# Validar sintaxis ANTES de instalar. visudo -c -f revisa el archivo aislado.
echo "🔎 Validando sintaxis con visudo..."
if ! visudo -c -f "$TMP_FILE"; then
  echo "❌ Sintaxis inválida. No se instaló nada." >&2
  exit 1
fi

# Instalar con dueño root:root y permisos 0440 (requisito de sudoers.d).
install -o root -g root -m 0440 "$TMP_FILE" "$SUDOERS_FILE"
echo "✅ Instalado: $SUDOERS_FILE"

# Re-validar el conjunto completo de sudoers (incluye el archivo recién puesto).
if visudo -c >/dev/null; then
  echo "✅ Configuración global de sudoers válida."
else
  echo "⚠️  visudo -c reportó problemas en el conjunto global. Revisa /etc/sudoers.d/." >&2
  exit 1
fi

echo
echo "Para verificar (como ${DEPLOY_USER}, NO debe pedir password):"
echo "  sudo ${SYSTEMCTL} restart pulse-dashboard"
