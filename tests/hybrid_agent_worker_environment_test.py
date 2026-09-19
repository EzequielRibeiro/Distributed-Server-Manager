#!/usr/bin/env python3
from pathlib import Path
import os
import subprocess
import tempfile


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


def _run_loader(config_text: str):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        conf = root / "config" / "providers" / "steam.conf"
        conf.parent.mkdir(parents=True)
        conf.write_text(config_text, encoding="utf-8")
        script = ROOT / "dashboard" / "workers" / "steam_env.sh"
        completed = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; load_worker_steam_user "$2"; printf "%s|%s" "$DSM_STEAM_USER" "${STEAM_PASSWORD-unset}"',
                "_",
                str(script),
                str(root),
            ],
            capture_output=True,
            text=True,
            check=False,
            env={key: value for key, value in os.environ.items() if key not in {"DSM_STEAM_USER", "STEAM_PASSWORD"}},
        )
        return completed


def test_worker_steam_user_loader_reads_only_account_name():
    completed = _run_loader(
        'DSM_STEAM_USER="_zeca_912"\n'
        'STEAM_PASSWORD="must-not-be-loaded"\n'
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "_zeca_912|unset"


def test_worker_steam_user_loader_rejects_shell_syntax():
    completed = _run_loader('DSM_STEAM_USER="$(id)"\n')
    assert completed.returncode != 0
    assert "DSM_STEAM_USER inválido" in completed.stderr


def test_supervisor_loads_steam_user_before_workers_start():
    text = WORKER.read_text(encoding="utf-8")
    load_index = text.index('load_worker_steam_user "${DSM_ROOT}"')
    worker_index = text.index("start_python_worker hybrid_agent_worker.py")
    assert load_index < worker_index


def test_hybrid_runtime_sets_game_data_root_before_runtime_imports():
    source = (
        ROOT / "dashboard" / "workers" / "hybrid_agent_worker.py"
    ).read_text(encoding="utf-8")
    state_index = source.index('os.environ.setdefault("CAPIVARA_AGENT_STATE_DIR"')
    game_data_index = source.index('os.environ.setdefault("CAPIVARA_GAME_DATA_ROOT"')
    import_index = source.index("from agent_instance_runtime_repository import")
    assert state_index < game_data_index < import_index
    assert 'str(_HYBRID_STATE / "game-data")' in source
