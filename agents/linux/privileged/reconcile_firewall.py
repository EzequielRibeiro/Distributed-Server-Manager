#!/usr/bin/env python3
"""Root-owned reconciliation of Capivara-managed host firewall rules."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
REQUEST_DIR = STATE_DIR / "privileged-firewall"
_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_NUMBERED = re.compile(r"^\[\s*(\d+)\]\s+(.*)$")
_TARGET = re.compile(r"^(\d{1,5})/(tcp|udp)(?:\s|$)", re.IGNORECASE)
_LEGACY_CAPIVARA_COMMENT = re.compile(r"^Capivara(?:\s|$)", re.IGNORECASE)
Runner = Callable[[list[str], int], tuple[int, str, str]]


def _default_runner(command: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise ValueError(f"invalid {label}")
    return text


def _rule_comment(instance_id: str, name: str, protocol: str, port: int) -> str:
    return f"capivara:{_token(instance_id, 'instance_id')}:{_token(name, 'port name')}:{protocol}:{port}"


def _validate_rules(instance_id: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("firewall rules must be a list")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("firewall rule must be an object")
        name = _token(raw.get("name"), "port name")
        protocol = str(raw.get("protocol") or "").strip().lower()
        if protocol not in {"tcp", "udp"}:
            raise ValueError("firewall protocol must be tcp or udp")
        try:
            port = int(raw.get("port"))
        except (TypeError, ValueError) as exc:
            raise ValueError("firewall port must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("firewall port must be between 1 and 65535")
        key = (protocol, port, name)
        if key in seen:
            raise ValueError("duplicate firewall rule")
        seen.add(key)
        result.append({"name": name, "protocol": protocol, "port": port,
                       "comment": _rule_comment(instance_id, name, protocol, port)})
    return result


def _ufw_active(runner: Runner) -> bool:
    code, stdout, _ = runner(["ufw", "status"], 10)
    return code == 0 and stdout.strip().lower().startswith("status: active")


def _listed_ufw_rules(runner: Runner) -> list[dict[str, Any]]:
    code, stdout, stderr = runner(["ufw", "status", "numbered"], 10)
    if code != 0:
        raise RuntimeError((stderr or stdout or "ufw status numbered failed")[:2000])
    result: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        match = _NUMBERED.match(line.strip())
        if not match:
            continue
        number = int(match.group(1))
        body = match.group(2)
        marker = body.find("#")
        comment = body[marker + 1:].strip() if marker >= 0 else ""
        target_text = body[:marker].strip() if marker >= 0 else body.strip()
        target = _TARGET.match(target_text)
        port = int(target.group(1)) if target else None
        protocol = target.group(2).lower() if target else None
        result.append({
            "number": number,
            "port": port,
            "protocol": protocol,
            "comment": comment,
        })
    return result


def _owned_ufw_rules(listed: list[dict[str, Any]], instance_id: str) -> dict[str, list[int]]:
    prefix = f"capivara:{instance_id}:"
    result: dict[str, list[int]] = {}
    for item in listed:
        comment = str(item.get("comment") or "")
        if comment.startswith(prefix):
            result.setdefault(comment, []).append(int(item["number"]))
    return result


def _legacy_migration_numbers(
    listed: list[dict[str, Any]],
    desired: list[dict[str, Any]],
    existing_owned: dict[str, list[int]],
) -> dict[str, list[int]]:
    """Return legacy Capivara rules that can be safely replaced by owned rules.

    Migration is intentionally narrow: only a numbered UFW rule with a legacy
    Capivara comment and the exact desired protocol/port pair is eligible.
    Rules without a Capivara marker, malformed targets, or already-owned rules
    are never adopted or removed.
    """
    result: dict[str, list[int]] = {}
    for wanted in desired:
        comment = wanted["comment"]
        if comment in existing_owned:
            continue
        protocol = wanted["protocol"]
        port = wanted["port"]
        matches = [
            int(item["number"])
            for item in listed
            if item.get("protocol") == protocol
            and item.get("port") == port
            and _LEGACY_CAPIVARA_COMMENT.match(str(item.get("comment") or ""))
            and not str(item.get("comment") or "").lower().startswith("capivara:")
        ]
        if matches:
            result[comment] = matches
    return result


def reconcile_ufw(instance_id: str, desired: list[dict[str, Any]], runner: Runner = _default_runner) -> dict[str, Any]:
    if not _ufw_active(runner):
        if desired:
            raise RuntimeError("no supported active Linux firewall backend; UFW is not active")
        return {"backend": "none", "changed": False, "rules": []}

    listed = _listed_ufw_rules(runner)
    existing = _owned_ufw_rules(listed, instance_id)
    wanted = {item["comment"]: item for item in desired}
    legacy = _legacy_migration_numbers(listed, desired, existing)

    delete_numbers = sorted(
        {
            number
            for comment, numbers in existing.items()
            if comment not in wanted
            for number in numbers
        }
        | {
            number
            for numbers in legacy.values()
            for number in numbers
        },
        reverse=True,
    )

    changed = False
    for number in delete_numbers:
        code, stdout, stderr = runner(["ufw", "--force", "delete", str(number)], 15)
        if code != 0:
            raise RuntimeError((stderr or stdout or f"failed to delete Capivara UFW rule {number}")[:2000])
        changed = True

    for comment, item in wanted.items():
        if comment in existing and comment not in legacy:
            continue
        code, stdout, stderr = runner(
            ["ufw", "allow", f"{item['port']}/{item['protocol']}", "comment", comment], 15
        )
        if code != 0:
            raise RuntimeError((stderr or stdout or "failed to create Capivara UFW rule")[:2000])
        changed = True

    return {"backend": "ufw", "changed": changed,
            "rules": [{k: item[k] for k in ("name", "protocol", "port", "comment")} for item in desired]}


def _atomic_json(
    path: Path,
    payload: dict[str, Any],
    *,
    owner: tuple[int, int] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temp, 0o600)
        if owner is not None:
            os.chown(temp, owner[0], owner[1])
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def run(instance_id: str, runner: Runner = _default_runner) -> dict[str, Any]:
    instance_id = _token(instance_id, "instance_id")
    request_path = REQUEST_DIR / f"{instance_id}.request.json"
    result_path = REQUEST_DIR / f"{instance_id}.result.json"
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict) or request.get("kind") != "CapivaraPrivilegedFirewallRequest":
            raise ValueError("invalid privileged firewall request")
        if _token(request.get("instance_id"), "instance_id") != instance_id:
            raise ValueError("firewall request instance mismatch")
        desired = _validate_rules(instance_id, request.get("rules"))
        operation = reconcile_ufw(instance_id, desired, runner)
        result = {"status": "completed", "instance_id": instance_id, "operation": operation}
    except Exception as exc:
        result = {"status": "failed", "instance_id": instance_id, "error": str(exc)[:2000]}
    owner = None
    try:
        request_stat = request_path.stat()
        owner = (request_stat.st_uid, request_stat.st_gid)
    except OSError:
        pass

    _atomic_json(
        result_path,
        result,
        owner=owner,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: reconcile_firewall.py INSTANCE_ID", file=sys.stderr)
        return 2
    result = run(args[0])
    if result.get("status") != "completed":
        print(result.get("error") or "firewall reconciliation failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
