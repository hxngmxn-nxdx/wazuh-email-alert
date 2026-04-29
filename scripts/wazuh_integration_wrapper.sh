#!/usr/bin/env bash
set -euo pipefail

# Wrapper para integração customizada do Wazuh.
# O Wazuh chama este script passando o caminho do alerta JSON como primeiro argumento.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAILER="${SCRIPT_DIR}/wazuh_html_mailer.py"

ALERT_FILE="${1:-}"
TO_ADDR="${WAZUH_MAIL_TO:-soc@empresa.com}"
FROM_ADDR="${WAZUH_MAIL_FROM:-wazuh@empresa.com}"
SUBJECT_PREFIX="${WAZUH_MAIL_SUBJECT_PREFIX:-Wazuh Security Alert}"
NO_SEND="${WAZUH_MAIL_NO_SEND:-0}"

if [[ -z "${ALERT_FILE}" ]]; then
  echo "Usage: $0 <alert-json-file>" >&2
  exit 2
fi

if [[ ! -f "${ALERT_FILE}" ]]; then
  echo "Alert file not found: ${ALERT_FILE}" >&2
  exit 1
fi

if [[ ! -f "${MAILER}" ]]; then
  echo "Mailer not found: ${MAILER}" >&2
  exit 1
fi

EXTRA_ARGS=()
if [[ "${NO_SEND}" == "1" ]]; then
  EXTRA_ARGS+=(--no-send)
fi

/usr/bin/python3 "${MAILER}" \
  --input "${ALERT_FILE}" \
  --to "${TO_ADDR}" \
  --from "${FROM_ADDR}" \
  --subject-prefix "${SUBJECT_PREFIX}" \
  "${EXTRA_ARGS[@]}"
