#!/usr/bin/env python3
"""Remote Linux Agent bootstrap over SSH.

SSH is intentionally limited to first-install bootstrap. After enrollment,
normal Controller/Agent communication uses the authenticated Agent protocol.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


class AgentDeployError(RuntimeError):
    """Safe administrator-facing deployment failure."""


@dataclass(frozen=True)
class SSHDeployOptions:
    host: str
    ssh_user: str
    ssh_port: int = 22
    identity_file: str | None = None
    connect_timeout: int = 10


@dataclass(frozen=True)
class SSHResult:
    returncode: int
    stdout: str
    stderr: str


SSHRunner = Callable[[Sequence[str], str | None, int | None], SSHResult]


_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def validate_host(value: str) -> str:
    host = str(value or "").strip()
    if not host or not _HOST_RE.fullmatch(host):
        raise AgentDeployError("invalid SSH host")
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        labels = candidate.rstrip(".").split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            for label in labels
        ):
            raise AgentDeployError("invalid SSH host")
    return candidate


def validate_ssh_user(value: str) -> str:
    user = str(value or "").strip()
    if not _USER_RE.fullmatch(user):
        raise AgentDeployError("invalid SSH user")
    return user


def _default_runner(argv: Sequence[str], stdin_text: str | None, timeout: int | None) -> SSHResult:
    completed = subprocess.run(
        list(argv),
        input=stdin_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return SSHResult(completed.returncode, completed.stdout, completed.stderr)


def build_ssh_argv(options: SSHDeployOptions, remote_command: str) -> list[str]:
    host = validate_host(options.host)
    user = validate_ssh_user(options.ssh_user)
    if not 1 <= int(options.ssh_port) <= 65535:
        raise AgentDeployError("ssh_port must be between 1 and 65535")
    if int(options.connect_timeout) < 1 or int(options.connect_timeout) > 300:
        raise AgentDeployError("connect_timeout must be between 1 and 300 seconds")

    argv = [
        "ssh",
        "-p",
        str(int(options.ssh_port)),
        "-o",
        f"ConnectTimeout={int(options.connect_timeout)}",
        "-o",
        "BatchMode=yes",
    ]
    if options.identity_file:
        identity = Path(os.path.expanduser(str(options.identity_file))).resolve()
        if not identity.is_file():
            raise AgentDeployError(f"SSH identity file not found: {identity}")
        argv.extend(["-i", str(identity)])
    argv.extend([f"{user}@{host}", remote_command])
    return argv


def _run_ssh(
    options: SSHDeployOptions,
    remote_command: str,
    *,
    runner: SSHRunner,
    stdin_text: str | None = None,
    timeout: int | None = None,
) -> SSHResult:
    if shutil.which("ssh") is None and runner is _default_runner:
        raise AgentDeployError("OpenSSH client not found")
    argv = build_ssh_argv(options, remote_command)
    try:
        result = runner(argv, stdin_text, timeout)
    except subprocess.TimeoutExpired as exc:
        raise AgentDeployError("SSH operation timed out") from exc
    except OSError as exc:
        raise AgentDeployError(f"unable to execute SSH client: {exc}") from exc
    return result


def preflight_ssh(options: SSHDeployOptions, *, runner: SSHRunner = _default_runner) -> dict[str, Any]:
    command = (
        "set -eu; "
        "test \"$(uname -s)\" = Linux; "
        "command -v bash >/dev/null; "
        "command -v curl >/dev/null; "
        "command -v python3 >/dev/null; "
        "command -v sudo >/dev/null; "
        "sudo -n true; "
        "printf 'CAPIVARA_PREFLIGHT_OK\\n'; uname -m"
    )
    result = _run_ssh(options, command, runner=runner, timeout=options.connect_timeout + 10)
    if result.returncode != 0 or "CAPIVARA_PREFLIGHT_OK" not in result.stdout:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else "remote preflight failed"
        raise AgentDeployError(
            "SSH preflight failed (Linux, curl, bash, python3 and non-interactive sudo are required): "
            + reason
        )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    architecture = lines[-1] if lines else "unknown"
    return {"platform": "linux", "architecture": architecture}


def remote_agent_present(options: SSHDeployOptions, *, runner: SSHRunner = _default_runner) -> bool:
    result = _run_ssh(
        options,
        "test -f /var/lib/capivara-agent/identity.json -o -f /etc/capivara-agent/agent.conf",
        runner=runner,
        timeout=options.connect_timeout + 5,
    )
    return result.returncode == 0


def _bootstrap_stdin(controller_url: str, pairing_token: str, release_tag: str = "latest") -> str:
    payload = json.dumps(
        {
            "controller_url": controller_url,
            "pairing_token": pairing_token,
            "release_tag": release_tag,
        },
        separators=(",", ":"),
    )
    return f'''import json, os, subprocess, tempfile\npayload = json.loads({payload!r})\nurl = payload["controller_url"].rstrip("/") + "/agent/install.sh"\nfd, path = tempfile.mkstemp(prefix="capivara-agent-bootstrap-", suffix=".sh")\nos.close(fd)\ntry:\n    subprocess.run(["curl", "-fsSL", url, "-o", path], check=True)\n    os.chmod(path, 0o700)\n    env = os.environ.copy()\n    env["CAPIVARA_PAIRING_TOKEN"] = payload["pairing_token"]\n    env["CAPIVARA_RELEASE_TAG"] = payload["release_tag"]\n    subprocess.run([\n        "bash", path,\n        "--controller-url", payload["controller_url"],\n    ], check=True, env=env)\nfinally:\n    try:\n        os.unlink(path)\n    except FileNotFoundError:\n        pass\n'''


def bootstrap_agent(
    options: SSHDeployOptions,
    *,
    controller_url: str,
    pairing_token: str,
    release_tag: str = "latest",
    runner: SSHRunner = _default_runner,
    timeout: int = 900,
) -> None:
    controller_url = str(controller_url or "").strip().rstrip("/")
    pairing_token = str(pairing_token or "").strip()
    release_tag = str(release_tag or "latest").strip()
    if not controller_url.startswith(("http://", "https://")):
        raise AgentDeployError("controller_url must use http:// or https://")
    if not pairing_token:
        raise AgentDeployError("pairing token is required")
    if not release_tag:
        raise AgentDeployError("release tag is required")

    result = _run_ssh(
        options,
        "sudo -n python3 -",
        runner=runner,
        stdin_text=_bootstrap_stdin(controller_url, pairing_token, release_tag),
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else "remote Agent bootstrap failed"
        raise AgentDeployError("Agent bootstrap failed: " + reason)


def wait_for_agent_online(
    status_reader: Callable[[], dict[str, Any]],
    *,
    timeout: int = 180,
    interval: float = 2.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, int(timeout))
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = dict(status_reader() or {})
        if (
            str(latest.get("agent_status", "")).lower() == "active"
            and str(latest.get("health_status", "")).lower() == "online"
        ):
            return latest
        time.sleep(max(0.05, float(interval)))
    raise AgentDeployError(
        "Agent enrollment did not reach active/online before timeout"
        + (f" (last state: {latest})" if latest else "")
    )
