#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${STRATEGY_MEMORY_VENV:-/sandbox/.openclaw/workspace/.venvs/strategy-memory}"
PYTHON="$VENV_DIR/bin/python"
TORCH_CPU_WHEEL="${STRATEGY_MEMORY_TORCH_WHEEL:-/sandbox/.openclaw/workspace/wheels/torch-2.12.0+cpu-cp313-cp313-manylinux_2_28_aarch64.whl}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
  "$PYTHON" -m pip install --upgrade pip wheel >&2
fi

if ! "$PYTHON" -c 'import torch, sys; sys.exit(0 if "+cpu" in torch.__version__ else 1)' >/dev/null 2>&1; then
  if [ -f "$TORCH_CPU_WHEEL" ]; then
    "$PYTHON" -m pip install --force-reinstall --no-deps "$TORCH_CPU_WHEEL" >&2
  else
    "$PYTHON" -m pip install --no-deps --index-url https://download.pytorch.org/whl/cpu "torch==2.12.0+cpu" >&2
  fi
fi

if ! "$PYTHON" -c 'import sentence_transformers, psycopg, pgvector, docx, pypdf' >/dev/null 2>&1; then
  "$PYTHON" -m pip install --no-deps sentence-transformers==5.1.2 >&2
  "$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" >&2
fi

"$SCRIPT_DIR/start_postgres.sh" >&2

exec "$PYTHON" "$SCRIPT_DIR/mcp_server.py"
