from __future__ import annotations

import os
from pathlib import Path

MAX_LLM_CONTEXT_SIZE = 262144


def runtime_data_dir() -> Path:
    """Verzeichnis für persistente Runtime-Daten (User-Accounts, Settings, Jobs, Task-Board).

    Wird über die ENV ``AURORA_RUNTIME_DIR`` konfiguriert (z. B. ``/app/runtime`` in Docker).
    Fallback: das ``backend/`` Verzeichnis (altes Verhalten, für lokale ``python -m uvicorn``-Starts).
    """
    env_value = os.environ.get("AURORA_RUNTIME_DIR", "").strip()
    if env_value:
        path = Path(env_value)
    else:
        # backend/app/defaults.py  ->  parents[1] = backend/
        path = Path(__file__).resolve().parents[1]
    path.mkdir(parents=True, exist_ok=True)
    return path
