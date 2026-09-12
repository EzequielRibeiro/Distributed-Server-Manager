#!/usr/bin/env python3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "dashboard" / "workers" / "worker.sh"


def test_hybrid_worker_launch_exports_runtime_context():
    text = WORKER.read_text(encoding="utf-8")

    assert "start_python_worker_with_env hybrid_agent_worker.py" in text
    assert '"CAPIVARA_AGENT_MODE=hybrid"' in text
    assert '"CAPIVARA_DSM_ROOT=${DSM_ROOT}"' in text
    assert 'env "$@" python3 "${WORKERS_DIR}/${WORKER}"' in text


def test_hybrid_context_is_scoped_to_hybrid_worker():
    text = WORKER.read_text(encoding="utf-8")

    assert "start_python_worker automation_worker.py" in text
    assert "start_python_worker hybrid_customer_workspace_worker.py" in text
