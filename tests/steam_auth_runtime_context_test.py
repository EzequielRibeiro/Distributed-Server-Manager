#!/usr/bin/env python3
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "core" / "steam_auth.sh"
CAP = ROOT / "bin" / "cap"


def test_steam_auth_helper_has_valid_shell_syntax():
    completed = subprocess.run(
        ["bash", "-n", str(HELPER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_steam_auth_reads_only_safe_account_name():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        conf = root / "config" / "providers" / "steam.conf"
        marker = root / "must-not-exist"
        conf.parent.mkdir(parents=True)
        conf.write_text(
            'DSM_STEAM_USER="_zeca_912"\n'
            f'STEAM_PASSWORD="$(touch {marker})"\n',
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["bash", "-c", 'source "$1"; steam_auth_read_user "$2"', "_", str(HELPER), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "_zeca_912"
        assert not marker.exists()


def test_steam_auth_rejects_shell_syntax_in_account_name():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        conf = root / "config" / "providers" / "steam.conf"
        conf.parent.mkdir(parents=True)
        conf.write_text('DSM_STEAM_USER="$(id)"\n', encoding="utf-8")
        completed = subprocess.run(
            ["bash", "-c", 'source "$1"; steam_auth_read_user "$2"', "_", str(HELPER), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode != 0
        assert "DSM_STEAM_USER inválido" in completed.stderr


def test_hybrid_context_uses_dashboard_worker_and_dsm_home():
    with tempfile.TemporaryDirectory() as td:
        fakebin = Path(td) / "bin"
        fakebin.mkdir()
        systemctl = fakebin / "systemctl"
        systemctl.write_text("#!/usr/bin/env bash\nprintf 'capivara\\n'\n", encoding="utf-8")
        systemctl.chmod(0o755)
        env = os.environ | {"PATH": f"{fakebin}:{os.environ.get('PATH', '')}"}
        completed = subprocess.run(
            ["bash", "-c", 'source "$1"; steam_auth_runtime_context "$2" hybrid', "_", str(HELPER), "/opt/dsm"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.splitlines() == [
            "dsm-dashboard-worker.service",
            "capivara",
            "/opt/dsm",
            "/opt/dsm/runtime/hybrid-agent-state",
        ]


def test_runtime_steamcmd_is_resolved_through_agent_runtime():
    text = HELPER.read_text(encoding="utf-8")
    assert "from game_data_executor import _steamcmd; print(_steamcmd())" in text
    assert 'CAPIVARA_AGENT_STATE_DIR="${STATE_DIR}"' in text


def test_cap_steam_auth_no_longer_sources_provider_config_or_legacy_provider():
    text = CAP.read_text(encoding="utf-8")
    start = text.index("steam_command(){")
    end = text.index("\n}\n", start) + 3
    block = text[start:end]
    assert "core/steam_auth.sh" in block
    assert 'require_role "cap steam auth" agent hybrid' in block
    assert "installer/providers/steam.sh" not in block
    assert 'source "${conf}"' not in block
