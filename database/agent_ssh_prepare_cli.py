#!/usr/bin/env python3
"""One-time interactive preparation for Dashboard SSH Agent installs."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

try:
    import pwd
except ImportError:  # pragma: no cover - the command itself is Linux-only
    pwd = None  # type: ignore[assignment]

ROOT_DIR = Path(__file__).resolve().parents[1]
for candidate in (ROOT_DIR, ROOT_DIR / "core"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from agent_ssh_deploy import AgentDeployError, validate_host, validate_ssh_user


def _run(argv: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run interactively so password prompts remain inside SSH and sudo."""
    try:
        return subprocess.run(list(argv), check=check, text=True)
    except subprocess.CalledProcessError as exc:
        raise AgentDeployError(f"command failed with exit status {exc.returncode}: {argv[0]}") from exc
    except OSError as exc:
        raise AgentDeployError(f"unable to execute {argv[0]}: {exc}") from exc


def discover_dashboard_user() -> str:
    requested = str(os.environ.get("DSM_DASHBOARD_USER", "")).strip()
    if requested:
        return validate_ssh_user(requested)
    if shutil.which("systemctl"):
        result = subprocess.run(
            ["systemctl", "show", "dsm-dashboard.service", "-p", "User", "--value"],
            check=False, text=True, capture_output=True,
        )
        service_user = result.stdout.strip()
        if result.returncode == 0 and service_user:
            return validate_ssh_user(service_user)
    raise AgentDeployError(
        "unable to discover the dsm-dashboard service user; "
        "set DSM_DASHBOARD_USER and run the command again"
    )


def parse_target(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if raw.count("@") != 1:
        raise AgentDeployError("target must use USER@HOST, for example mine@192.168.15.55")
    user, host = raw.split("@", 1)
    return validate_ssh_user(user), validate_host(host)


def service_identity(service_user: str) -> tuple[Path, str]:
    if pwd is None:
        raise AgentDeployError("ssh-prepare is supported only on Linux Controllers")
    try:
        entry = pwd.getpwnam(service_user)
    except KeyError as exc:
        raise AgentDeployError(f"Dashboard service user does not exist: {service_user}") from exc
    home = Path(entry.pw_dir)
    if not home.is_absolute() or str(home) in {"/", "/nonexistent"}:
        raise AgentDeployError(f"Dashboard service user has no usable home directory: {home}")
    return home, entry.pw_name


def _as_user(service_user: str, argv: Sequence[str]) -> list[str]:
    return ["runuser", "-u", service_user, "--", *argv]


def ensure_identity(service_user: str, home: Path) -> Path:
    if pwd is None:
        raise AgentDeployError("ssh-prepare is supported only on Linux Controllers")
    ssh_dir = home / ".ssh"
    key = ssh_dir / "id_ed25519"
    entry = pwd.getpwnam(service_user)
    ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(ssh_dir, entry.pw_uid, entry.pw_gid)
    os.chmod(ssh_dir, 0o700)
    public_key = Path(f"{key}.pub")
    if key.exists() != public_key.exists():
        raise AgentDeployError(f"incomplete SSH identity found at {key}; repair it before continuing")
    if not key.exists():
        _run(_as_user(service_user, ["ssh-keygen", "-t", "ed25519", "-f", str(key), "-N", ""]))
    os.chmod(key, 0o600)
    os.chmod(public_key, 0o644)
    return key


def restricted_sudo_command(remote_user: str) -> str:
    user = shlex.quote(remote_user)
    rule_name = shlex.quote(f"/etc/sudoers.d/capivara-agent-{remote_user}")
    return (
        "set -eu; TRUE_BIN=$(command -v true); PYTHON_BIN=$(command -v python3); "
        "command -v sudo >/dev/null; command -v visudo >/dev/null; "
        "RULE_TMP=$(mktemp); trap 'rm -f \"$RULE_TMP\"' EXIT; sudo -v; "
        f"printf '%s ALL=(root) NOPASSWD: %s, %s -\\n' {user} \"$TRUE_BIN\" \"$PYTHON_BIN\" "
        ">\"$RULE_TMP\"; chmod 600 \"$RULE_TMP\"; sudo visudo -cf \"$RULE_TMP\"; "
        f"sudo install -o root -g root -m 440 \"$RULE_TMP\" {rule_name}; "
        f"sudo visudo -cf {rule_name}"
    )


def prepare(args: argparse.Namespace) -> None:
    if os.geteuid() != 0:
        raise AgentDeployError("run this preparation with sudo")
    if not 1 <= args.ssh_port <= 65535:
        raise AgentDeployError("ssh-port must be between 1 and 65535")
    remote_user, host = parse_target(args.target)
    service_user = discover_dashboard_user()
    home, service_user = service_identity(service_user)
    for command in ("runuser", "ssh", "ssh-copy-id", "ssh-keygen"):
        if shutil.which(command) is None:
            raise AgentDeployError(f"required command not found: {command}")

    print(f"Dashboard user : {service_user}")
    print(f"Remote target  : {remote_user}@{host}:{args.ssh_port}")
    key = ensure_identity(service_user, home)
    public_key = Path(f"{key}.pub")
    print(f"SSH identity   : {key}")
    print("Authorize the public key (the remote SSH password may be requested once).")
    common = ["-p", str(args.ssh_port), "-o", "StrictHostKeyChecking=accept-new"]
    _run(_as_user(service_user, ["ssh-copy-id", "-i", str(public_key), *common, f"{remote_user}@{host}"]))

    print("Install the restricted sudo rule (the remote sudo password may be requested once).")
    _run(_as_user(service_user, [
        "ssh", "-tt", "-i", str(key), *common,
        f"{remote_user}@{host}", restricted_sudo_command(remote_user),
    ]))

    print("Testing passwordless SSH and restricted non-interactive sudo...")
    test = _run(_as_user(service_user, [
        "ssh", "-i", str(key), *common, "-o", "BatchMode=yes",
        f"{remote_user}@{host}",
        "sudo -n true && printf 'import sys; sys.exit(0)\\n' | sudo -n python3 -",
    ]), check=False)
    if test.returncode != 0:
        raise AgentDeployError("final non-interactive SSH/sudo validation failed")
    print(f"SSH_READY {remote_user}@{host}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare passwordless, restricted SSH access for Dashboard Agent installation"
    )
    parser.add_argument("target", help="remote SSH target in USER@HOST format")
    parser.add_argument("--ssh-port", type=int, default=22)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        prepare(args)
    except AgentDeployError as exc:
        parser.exit(2, f"Erro: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
