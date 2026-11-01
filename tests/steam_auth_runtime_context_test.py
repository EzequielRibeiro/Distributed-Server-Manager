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


def test_services_pin_persistent_steam_session_home():
    hybrid = (ROOT / "systemd" / "dsm-dashboard-worker.service").read_text(encoding="utf-8")
    agent = (ROOT / "agents" / "linux" / "services" / "capivara-agent.service").read_text(encoding="utf-8")
    worker = (ROOT / "dashboard" / "workers" / "worker.sh").read_text(encoding="utf-8")
    assert "Environment=HOME=/opt/dsm" in hybrid
    assert "Environment=CAPIVARA_STEAM_HOME=/opt/dsm" in hybrid
    assert "Environment=HOME=/var/lib/capivara-agent" in agent
    assert "Environment=CAPIVARA_STEAM_HOME=/var/lib/capivara-agent" in agent
    assert '"CAPIVARA_STEAM_HOME=${DSM_ROOT}"' in worker


def test_auth_uses_same_persistent_home_and_probes_noninteractive_reuse():
    text = HELPER.read_text(encoding="utf-8")
    assert 'CAPIVARA_STEAM_HOME="${RUNTIME_HOME}"' in text
    assert "steam_auth_probe_reusable_session" in text
    assert "</dev/null 2>&1" in text
    assert "Sessão não interativa validada" in text


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


def _probe_fake_steamcmd(output: str, exit_code: int = 0) -> subprocess.CompletedProcess:
    """Exercise the actual shell probe without accessing Steam accounts."""
    with tempfile.TemporaryDirectory() as td:
        binary = Path(td) / "mock-steamcmd"
        # The response text is written to a file, never interpreted as code.
        response = Path(td) / "response.txt"
        response.write_text(output, encoding="utf-8")
        binary.write_text(
            '#!/usr/bin/env bash\ncat "$(dirname "$0")/response.txt"\n'
            f'exit {exit_code}\n', encoding="utf-8"
        )
        binary.chmod(0o700)
        return subprocess.run(
            ["bash", "-c", 'source "$1"; steam_auth_exec_as_runtime(){ shift 3; "$@"; }; steam_auth_probe_reusable_session tester /tmp /tmp "$2" account' , "_", str(HELPER), str(binary)],
            capture_output=True, text=True, check=False,
        )


def test_noninteractive_auth_probe_requires_actual_login_marker():
    for output in (
        "Loading Steam API...OK\nLogging in user 'account' to Steam Public...OK\n",
        "Logged in OK\n",
    ):
        result = _probe_fake_steamcmd(output)
        assert result.returncode == 0, result.stderr


def test_noninteractive_auth_probe_fails_closed_on_zero_exit_without_login():
    for output in (
        "Loading Steam API...OK\n",
        "Connecting anonymously to Steam Public...OK\nWaiting for user info...OK\n",
        "Waiting for user info...OK\n",
        "ERROR! Login Failure: Invalid Password\n",
        "Steam Guard code required\n",
        "ERROR! Download item 2289456201 failed (Failure).\n",
    ):
        result = _probe_fake_steamcmd(output)
        assert result.returncode != 0, output
        assert result.stdout == ""  # no sensitive SteamCMD output


def test_noninteractive_auth_probe_rejects_nonzero_exit_with_success_marker():
    result = _probe_fake_steamcmd("Logging in user 'account' to Steam Public...OK\n", exit_code=1)
    assert result.returncode != 0
