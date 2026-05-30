#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
SERVICE_NAME="${SERVICE_NAME:-sem6000-bridge}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-${USER}}}"
SERVICE_GROUP="${SERVICE_GROUP:-${SERVICE_USER}}"
CONFIG_DIR="${CONFIG_DIR:-/etc/sem6000-bridge}"
CONFIG_FILE="${CONFIG_FILE:-${CONFIG_DIR}/config.toml}"
VENV_DIR="${VENV_DIR:-${PROJECT_DIR}/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BRIDGE_SCRIPT="${PROJECT_DIR}/codis/usa_sem6000_thingsboard_mqtt.py"
EXAMPLE_CONFIG="${PROJECT_DIR}/codis/config/sem6000-bridge.example.toml"
SEM6000_REPO_URL="${SEM6000_REPO_URL:-https://github.com/Matthias-pixel/python3-voltcraft-sem6000.git}"
SEM6000_REPO_DIR="${PROJECT_DIR}/github2/python3-voltcraft-sem6000"
SEM6000_REQUIREMENTS="${PROJECT_DIR}/github2/python3-voltcraft-sem6000/requirements.txt"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ ! -f "${BRIDGE_SCRIPT}" ]]; then
  echo "No trobo el bridge a ${BRIDGE_SCRIPT}" >&2
  exit 1
fi

if [[ ! -f "${EXAMPLE_CONFIG}" ]]; then
  echo "No trobo la config d'exemple a ${EXAMPLE_CONFIG}" >&2
  exit 1
fi

echo "Projecte: ${PROJECT_DIR}"
echo "Usuari servei: ${SERVICE_USER}:${SERVICE_GROUP}"
echo "Config: ${CONFIG_FILE}"

if [[ ! -d "${SEM6000_REPO_DIR}" ]]; then
  mkdir -p "$(dirname "${SEM6000_REPO_DIR}")"
  git clone "${SEM6000_REPO_URL}" "${SEM6000_REPO_DIR}"
fi

if [[ ! -f "${SEM6000_REQUIREMENTS}" ]]; then
  echo "No trobo requirements SEM6000 a ${SEM6000_REQUIREMENTS}" >&2
  exit 1
fi

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install paho-mqtt
"${VENV_DIR}/bin/python" -m pip install -r "${SEM6000_REQUIREMENTS}"

if getent group bluetooth >/dev/null 2>&1; then
  sudo usermod -aG bluetooth "${SERVICE_USER}" || true
fi

BLUEPY_HELPER="$(find "${VENV_DIR}" -path "*/bluepy/bluepy-helper" -type f | head -n 1 || true)"
if [[ -n "${BLUEPY_HELPER}" ]] && command -v setcap >/dev/null 2>&1; then
  sudo setcap cap_net_raw,cap_net_admin+eip "${BLUEPY_HELPER}" || true
fi

sudo install -d -m 750 -o root -g "${SERVICE_GROUP}" "${CONFIG_DIR}"
CONFIG_CREATED=0
if [[ ! -f "${CONFIG_FILE}" ]]; then
  sudo install -m 640 -o root -g "${SERVICE_GROUP}" "${EXAMPLE_CONFIG}" "${CONFIG_FILE}"
  CONFIG_CREATED=1
  echo "He creat ${CONFIG_FILE}; edita gateway_access_token i address abans d'arrencar."
fi

sudo tee "${SERVICE_FILE}" >/dev/null <<SERVICE
[Unit]
Description=SEM6000 ThingsBoard MQTT bridge
Wants=network-online.target bluetooth.service
After=network-online.target bluetooth.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
SupplementaryGroups=bluetooth
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV_DIR}/bin/python ${BRIDGE_SCRIPT} --config ${CONFIG_FILE}
Restart=always
RestartSec=10
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"

if [[ "${CONFIG_CREATED}" == "0" ]]; then
  "${VENV_DIR}/bin/python" "${BRIDGE_SCRIPT}" --config "${CONFIG_FILE}" --check-config
  sudo systemctl restart "${SERVICE_NAME}.service"
  echo "Servei arrencat. Logs: journalctl -u ${SERVICE_NAME} -f"
else
  echo "Servei habilitat pero no arrencat perque la config es nova."
  echo "Despres d'editar-la: sudo systemctl start ${SERVICE_NAME}"
fi
