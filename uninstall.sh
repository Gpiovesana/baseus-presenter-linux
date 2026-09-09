#!/bin/bash
set -euo pipefail

# Usa o Python do sistema: a venv será removida durante a desinstalação.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec /usr/bin/python3 "$SCRIPT_DIR/app/uninstall.py" "$SCRIPT_DIR"
