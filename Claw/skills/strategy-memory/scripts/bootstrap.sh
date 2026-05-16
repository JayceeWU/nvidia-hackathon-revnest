#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${STRATEGY_MEMORY_VENV:-/sandbox/.openclaw/workspace/.venvs/strategy-memory}"
PYTHON="$VENV_DIR/bin/python"
TORCH_CPU_WHEEL="${STRATEGY_MEMORY_TORCH_WHEEL:-/sandbox/.openclaw/workspace/wheels/torch-2.12.0+cpu-cp313-cp313-manylinux_2_28_aarch64.whl}"
MODEL_DIR="${STRATEGY_MEMORY_MODEL_DIR:-/sandbox/.openclaw/workspace/.cache/strategy-memory/models/all-MiniLM-L6-v2}"

python3 -m venv "$VENV_DIR"
"$PYTHON" -m pip install --upgrade pip wheel
if ! "$PYTHON" -c 'import torch, sys; sys.exit(0 if "+cpu" in torch.__version__ else 1)' >/dev/null 2>&1; then
  if [ -f "$TORCH_CPU_WHEEL" ]; then
    "$PYTHON" -m pip install --force-reinstall --no-deps "$TORCH_CPU_WHEEL"
  else
    "$PYTHON" -m pip install --no-deps --index-url https://download.pytorch.org/whl/cpu "torch==2.12.0+cpu"
  fi
fi
"$PYTHON" -m pip install --no-deps sentence-transformers==5.1.2
"$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt"
STRATEGY_MEMORY_MODEL_DIR="$MODEL_DIR" "$PYTHON" - <<'PY'
import os
from pathlib import Path
from sentence_transformers import SentenceTransformer
model_dir = Path(os.getenv("STRATEGY_MEMORY_MODEL_DIR", "/sandbox/.openclaw/workspace/.cache/strategy-memory/models/all-MiniLM-L6-v2"))
model_name = str(model_dir) if (model_dir / "modules.json").exists() else "sentence-transformers/all-MiniLM-L6-v2"
SentenceTransformer(model_name)
print("strategy-memory bootstrap complete")
PY
