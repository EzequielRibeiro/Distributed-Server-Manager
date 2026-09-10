"""Capivara-managed Windows Firewall rules."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable


_ALLOWED_PROTOCOLS = {
    "tcp": "TCP",
    "udp": "UDP",
}

_ALLOWED_EXPOSURE = {
    "public",
    "private",
    "none",
}

_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_GROUP = "Capivara Managed Game Firewall"

Runner = Callable[[list[str], int], tuple[int, str, str]]


def _runner(command: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            ),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)

    return (
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )


def _token(
    value: Any,
    label: str,
    max_length: int = 191,
) -> str:
    text = str(value or "").strip()

    if (
        not text
        or len(text) > max_length
        or not _TOKEN.fullmatch(text)
    ):
        raise ValueError(f"invalid {label}")

    return text


def public_rules(spec: dict[str, Any]) -> list[dict[str, Any]]:
    policy = spec.get("catalog_runtime_policy")

    if not isinstance(policy, dict):
        raise ValueError(
            "catalog runtime policy is required for managed firewall"
        )

    exposure = policy.get("network_exposure")

    if not isinstance(exposure, list):
        raise ValueError(
            "catalog network exposure is required for managed firewall"
        )

    ports = spec.get("ports")

    if not isinstance(ports, dict):
        raise ValueError(
            "runtime ports are required for managed firewall"
        )

    result = []
    seen = set()

    for raw in exposure:
        if not isinstance(raw, dict):
            raise ValueError(
                "invalid catalog network exposure entry"
            )

        name = _token(
            raw.get("name"),
            "port name",
            64,
        )

        if name in seen:
            raise ValueError(
                f"duplicate catalog network exposure: {name}"
            )

        seen.add(name)

        protocol = str(
            raw.get("protocol") or ""
        ).strip().lower()

        scope = str(
            raw.get("exposure") or "none"
        ).strip().lower()

        if protocol not in _ALLOWED_PROTOCOLS:
            raise ValueError(
                f"invalid protocol for {name}"
            )

        if scope not in _ALLOWED_EXPOSURE:
            raise ValueError(
                f"invalid exposure for {name}"
            )

        binding = ports.get(name)

        if not isinstance(binding, dict):
            raise ValueError(
                f"resolved port is unavailable for {name}"
            )

        try:
            port = int(binding.get("port"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid resolved port for {name}"
            ) from exc

        if not 1 <= port <= 65535:
            raise ValueError(
                f"resolved port outside TCP/UDP range for {name}"
            )

        resolved_protocol = str(
            binding.get("protocol") or ""
        ).strip().lower()

        if resolved_protocol != protocol:
            raise ValueError(
                f"resolved protocol mismatch for {name}: "
                f"catalog={protocol} "
                f"resolved={resolved_protocol}"
            )

        if scope == "public":
            result.append(
                {
                    "name": name,
                    "protocol": protocol,
                    "port": port,
                }
            )

    return result


def _display_name(
    instance_id: str,
    name: str,
    protocol: str,
    port: int,
) -> str:
    return (
        f"Capivara:{instance_id}:"
        f"{name}:{protocol}:{port}"
    )


def _powershell(script: str) -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]


def _existing(
    instance_id: str,
    runner: Runner,
) -> list[dict[str, str]]:
    prefix = f"Capivara:{instance_id}:"

    script = (
        "$ErrorActionPreference='Stop';"
        f"$prefix={json.dumps(prefix)};"
        f"$group={json.dumps(_GROUP)};"
        "$items=Get-NetFirewallRule "
        "-Group $group "
        "-ErrorAction SilentlyContinue | "
        "Where-Object {"
        "$_.DisplayName -like ($prefix + '*')"
        "} | Select-Object DisplayName,Name;"
        "@($items) | ConvertTo-Json -Compress"
    )

    code, stdout, stderr = runner(
        _powershell(script),
        30,
    )

    if code != 0:
        raise RuntimeError(
            (
                stderr
                or stdout
                or "failed to enumerate Windows Firewall rules"
            )[:2000]
        )

    text = stdout.strip()

    if not text:
        return []

    try:
        value = json.loads(text)
    except ValueError as exc:
        raise RuntimeError(
            "Windows Firewall returned invalid rule inventory"
        ) from exc

    if isinstance(value, dict):
        value = [value]

    if not isinstance(value, list):
        raise RuntimeError(
            "Windows Firewall returned invalid rule inventory"
        )

    result = []

    for item in value:
        if not isinstance(item, dict):
            continue

        display_name = str(
            item.get("DisplayName") or ""
        ).strip()

        rule_id = str(
            item.get("Name") or ""
        ).strip()

        if (
            display_name.startswith(prefix)
            and rule_id
        ):
            result.append(
                {
                    "display_name": display_name,
                    "rule_id": rule_id,
                }
            )

    return result


def reconcile(
    spec: dict[str, Any],
    *,
    rules: list[dict[str, Any]] | None = None,
    runner: Runner = _runner,
) -> dict[str, Any]:
    instance_id = _token(
        spec.get("instance_id"),
        "instance_id",
    )

    # Legacy Windows runtime records created before managed firewall support
    # have no catalog_runtime_policy. Keep those runtimes operational without
    # implicitly opening any port. Once a catalog policy exists, exposure is
    # mandatory and public_rules() remains fail-closed.
    if rules is None and spec.get("catalog_runtime_policy") is None:
        return {
            "backend": "windows-firewall",
            "changed": False,
            "rules": [],
            "managed": False,
        }

    desired = (
        public_rules(spec)
        if rules is None
        else list(rules)
    )

    wanted = {}

    for raw in desired:
        if not isinstance(raw, dict):
            raise ValueError(
                "invalid firewall rule"
            )

        name = _token(
            raw.get("name"),
            "port name",
            64,
        )

        protocol = str(
            raw.get("protocol") or ""
        ).strip().lower()

        if protocol not in _ALLOWED_PROTOCOLS:
            raise ValueError(
                "invalid firewall protocol"
            )

        try:
            port = int(raw.get("port"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "firewall port must be an integer"
            ) from exc

        if not 1 <= port <= 65535:
            raise ValueError(
                "firewall port must be between 1 and 65535"
            )

        display_name = _display_name(
            instance_id,
            name,
            protocol,
            port,
        )

        if display_name in wanted:
            raise ValueError(
                "duplicate firewall rule"
            )

        wanted[display_name] = {
            "name": name,
            "protocol": protocol,
            "port": port,
            "display_name": display_name,
        }

    existing = _existing(
        instance_id,
        runner,
    )

    existing_names = {
        item["display_name"]: item
        for item in existing
    }

    changed = False

    for display_name, item in existing_names.items():
        if display_name in wanted:
            continue

        script = (
            "$ErrorActionPreference='Stop';"
            f"$id={json.dumps(item['rule_id'])};"
            "Remove-NetFirewallRule "
            "-Name $id"
        )

        code, stdout, stderr = runner(
            _powershell(script),
            30,
        )

        if code != 0:
            raise RuntimeError(
                (
                    stderr
                    or stdout
                    or "failed to remove Capivara firewall rule"
                )[:2000]
            )

        changed = True

    for display_name, item in wanted.items():
        if display_name in existing_names:
            continue

        protocol = _ALLOWED_PROTOCOLS[
            item["protocol"]
        ]

        script = (
            "$ErrorActionPreference='Stop';"
            f"$name={json.dumps(display_name)};"
            f"$group={json.dumps(_GROUP)};"
            f"$protocol={json.dumps(protocol)};"
            f"$port={item['port']};"
            "New-NetFirewallRule "
            "-DisplayName $name "
            "-Group $group "
            "-Direction Inbound "
            "-Action Allow "
            "-Enabled True "
            "-Profile Any "
            "-Protocol $protocol "
            "-LocalPort $port "
            "| Out-Null"
        )

        code, stdout, stderr = runner(
            _powershell(script),
            30,
        )

        if code != 0:
            raise RuntimeError(
                (
                    stderr
                    or stdout
                    or "failed to create Capivara firewall rule"
                )[:2000]
            )

        changed = True

    return {
        "backend": "windows-firewall",
        "changed": changed,
        "rules": list(wanted.values()),
    }


def remove(
    spec: dict[str, Any],
    *,
    runner: Runner = _runner,
) -> dict[str, Any]:
    return reconcile(
        spec,
        rules=[],
        runner=runner,
    )


__all__ = [
    "public_rules",
    "reconcile",
    "remove",
]
