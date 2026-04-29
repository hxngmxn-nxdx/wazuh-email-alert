#!/usr/bin/env bash
set -euo pipefail

# Compatibilidade com o nome antigo.
# Toda a configuração fica em scripts/custom-email-html para evitar duplicação.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/custom-email-html" "$@"
