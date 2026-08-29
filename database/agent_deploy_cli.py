#!/usr/bin/env python3
"""Administrative CLI for bootstrapping one or many Agents over OpenSSH."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
for candidate in (ROOT_DIR, ROOT_DIR / "core", ROOT_DIR / "database"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from agent_batch_targets import load_csv_targets, normalize_concurrency, target_from_values
from agent_deploy_topology import validate_deploy_location
from agent_installation_preconfiguration import AgentInstallationPreconfigurationRepository, normalize_preconfiguration
from agent_pairing_repository import AgentPairingRepository
from agent_ssh_deploy import (
    AgentDeployError,
    SSHDeployOptions,
    bootstrap_agent,
    bootstrap_agent_package,
    bootstrap_windows_agent_ssh,
    preflight_ssh,
    preflight_windows_ssh,
    remote_agent_present,
    remote_windows_agent_present_ssh,
    wait_for_agent_online,
)
from alert_repository import AlertSession, dialect_for_backend
from runtime_backend import backend_from_environment


def _active_controller_id(backend, requested):
    d = dialect_for_backend(backend)
    ph = d.placeholder
    with backend.connect() as c:
        s = AlertSession(backend, c)
        try:
            if requested:
                row = s.execute(f"SELECT id,status FROM controllers WHERE id={ph}", (str(requested).strip(),)).fetchone()
                if row is None:
                    raise AgentDeployError(f"Controller not found: {requested}")
                if str(row["status"]).lower() != "active":
                    raise AgentDeployError("Controller must be active")
                return str(row["id"])
            rows = s.execute("SELECT id FROM controllers WHERE status='active' ORDER BY id").fetchall()
        finally:
            s.close()
    if not rows:
        raise AgentDeployError("no active Controller identity found")
    if len(rows) > 1:
        raise AgentDeployError("multiple active Controllers found; use --controller-id")
    return str(rows[0]["id"])


def _source_address_for_host(host):
    try:
        infos = socket.getaddrinfo(host, 9, type=socket.SOCK_DGRAM)
    except socket.gaierror as exc:
        raise AgentDeployError(f"unable to resolve Agent host: {host}") from exc
    for family, socktype, proto, _, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.connect(sockaddr)
            address = str(sock.getsockname()[0])
            if address and address not in {"0.0.0.0", "::"}:
                return address
        except OSError:
            pass
        finally:
            sock.close()
    raise AgentDeployError("unable to determine Controller address reachable by Agent")


def _controller_url(host, requested):
    explicit = str(requested or "").strip() or str(os.environ.get("DSM_CONTROLLER_URL", "")).strip()
    if explicit:
        if not explicit.startswith(("http://", "https://")):
            raise AgentDeployError("controller URL must use http:// or https://")
        return explicit.rstrip("/")
    address = _source_address_for_host(host)
    address = f"[{address}]" if ":" in address else address
    return f"http://{address}:{int(os.environ.get('DSM_DASHBOARD_PORT','8080') or '8080')}"


def _parse_port_range(value):
    raw = str(value or "").strip()
    if not raw:
        return None, None
    if raw.count("-") != 1:
        raise ValueError("--port-range must use START-END")
    try:
        start, end = map(int, raw.split("-", 1))
    except ValueError as exc:
        raise ValueError("--port-range must contain integer ports") from exc
    if not 1 <= start <= end <= 65535:
        raise ValueError("--port-range must satisfy 1 <= START <= END <= 65535")
    return start, end


def _preconfiguration(args):
    start, end = _parse_port_range(args.port_range)
    if start is None and args.port_protocol is not None:
        raise ValueError("--port-protocol requires --port-range")
    payload = {"agent_name": args.name}
    if start is not None:
        payload.update(port_start=start, port_end=end, port_protocol=args.port_protocol or "both")
    return normalize_preconfiguration(payload)


def _preconfiguration_from_args(args):
    return _preconfiguration(args)


def _annotate_pairing(backend, *, token_id, platform, region_id, datacenter_id):
    d = dialect_for_backend(backend)
    ph = d.placeholder
    with backend.transaction() as c:
        s = AlertSession(backend, c)
        try:
            columns = {str(r["name"]) for r in s.execute("PRAGMA table_info(agent_pairing_tokens)").fetchall()} if d.name == "sqlite" else set()
            assignments = []
            values = []
            for column, value in (("platform", platform), ("install_method", "ssh"), ("region_id", region_id), ("datacenter_id", datacenter_id)):
                if columns and column not in columns:
                    continue
                if value is None and column in {"region_id", "datacenter_id"}:
                    continue
                assignments.append(f"{column}={ph}")
                values.append(value)
            if assignments:
                values.append(token_id)
                s.execute("UPDATE agent_pairing_tokens SET " + ",".join(assignments) + f" WHERE id={ph}", tuple(values))
        finally:
            s.close()


def _json_timestamp(value):
    """Return a stable JSON-native representation for database timestamps."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def _status_reader(backend, token_id):
    d = dialect_for_backend(backend)
    ph = d.placeholder

    def read():
        with backend.connect() as c:
            s = AlertSession(backend, c)
            try:
                row = s.execute("SELECT agent_id,consumed_at FROM agent_pairing_tokens WHERE id=" + ph, (token_id,)).fetchone()
                if row is None:
                    raise AgentDeployError("pairing record disappeared during deployment")
                agent_id = str(row["agent_id"]) if row["agent_id"] else None
                payload = {"agent_id": agent_id, "pairing_consumed": bool(row["consumed_at"]), "agent_status": None, "health_status": None}
                if not agent_id:
                    return payload
                agent = s.execute(f"SELECT status,node_id,name FROM agents WHERE id={ph}", (agent_id,)).fetchone()
                runtime = s.execute(f"SELECT health_status,last_seen,hostname,address FROM agent_runtime_inventory WHERE agent_id={ph}", (agent_id,)).fetchone()
                if agent is not None:
                    payload.update(agent_status=str(agent["status"]), node_id=str(agent["node_id"]), name=str(agent["name"]))
                if runtime is not None:
                    payload.update(health_status=str(runtime["health_status"] or ""), last_seen=_json_timestamp(runtime["last_seen"]), hostname=runtime["hostname"], address=runtime["address"])
                return payload
            finally:
                s.close()

    return read


def deploy(args):
    backend = backend_from_environment()
    try:
        backend.initialize()
        options = SSHDeployOptions(
            host=args.host,
            ssh_user=args.ssh_user,
            ssh_port=args.ssh_port,
            identity_file=args.identity_file,
            password_file=args.password_file,
            connect_timeout=args.connect_timeout,
        )
        package_file = getattr(args, "package_file", None)
        release_tag = args.release_tag or "latest"
        if package_file and args.platform != "linux":
            raise AgentDeployError("--package-file is supported only for Linux Agents")
        controller_id = _active_controller_id(backend, args.controller_id)
        controller_url = _controller_url(args.host, args.controller_url)
        region_id, datacenter_id = validate_deploy_location(backend, region_id=args.region_id, datacenter_id=args.datacenter_id)
        preconfiguration = _preconfiguration(args)
        if args.platform == "windows":
            preflight = preflight_windows_ssh(options)
            present = remote_windows_agent_present_ssh(options)
            bootstrap = bootstrap_windows_agent_ssh
        else:
            preflight = preflight_ssh(options)
            present = remote_agent_present(options)
            bootstrap = bootstrap_agent
        if present:
            raise AgentDeployError("Capivara Agent installation already detected on remote host; refusing automatic reinstall")
        issued = AgentPairingRepository(backend).issue_token(
            controller_id=controller_id,
            created_by=os.environ.get("USER") or None,
            ttl_seconds=args.pairing_ttl,
        )
        _annotate_pairing(backend, token_id=issued.token_id, platform=args.platform, region_id=region_id, datacenter_id=datacenter_id)
        AgentInstallationPreconfigurationRepository(backend).save(issued.token_id, preconfiguration)
        if package_file:
            bootstrap_agent_package(options, controller_url=controller_url, pairing_token=issued.token, package_file=package_file, timeout=args.bootstrap_timeout)
        else:
            bootstrap(options, controller_url=controller_url, pairing_token=issued.token, release_tag=release_tag, timeout=args.bootstrap_timeout)
        online = wait_for_agent_online(_status_reader(backend, issued.token_id), timeout=args.heartbeat_timeout)
        applied = AgentInstallationPreconfigurationRepository(backend).get(issued.token_id)
        return {
            "deployment": "completed",
            "host": args.host,
            "ssh_user": args.ssh_user,
            "ssh_port": args.ssh_port,
            "controller_id": controller_id,
            "controller_url": controller_url,
            "region_id": region_id,
            "datacenter_id": datacenter_id,
            "preconfiguration": applied,
            "remote_platform": preflight.get("platform"),
            "remote_architecture": preflight.get("architecture"),
            "authentication": "password-file" if args.password_file else ("identity-file" if args.identity_file else "ssh-agent/default-key"),
            "agent_id": online.get("agent_id"),
            "node_id": online.get("node_id"),
            "agent_status": online.get("agent_status"),
            "health_status": online.get("health_status"),
            "last_seen": _json_timestamp(online.get("last_seen")),
        }
    finally:
        backend.close()


def build_parser():
    p = argparse.ArgumentParser(
        description="Deploy one or many Capivara Linux/Windows Agents over OpenSSH",
        epilog=(
            "Passwords are never accepted as CLI values or CSV fields. Use --password-file PATH "
            "for a protected 0600 file, or --identity-file PATH for an SSH private key."
        ),
    )
    p.add_argument("host", nargs="?", help="single remote Agent host")
    p.add_argument("--hosts-file", help="CSV containing batch targets")
    p.add_argument("--platform", choices=("linux", "windows"), default="linux")
    p.add_argument("--ssh-user", help="SSH bootstrap user; may be supplied per CSV row")
    p.add_argument("--ssh-port", type=int, default=22)
    auth = p.add_mutually_exclusive_group()
    auth.add_argument("--identity-file", help="Controller-local SSH private key")
    auth.add_argument("--password-file", help="protected file containing only the SSH password; mode 0600 or stricter")
    p.add_argument("--controller-id")
    p.add_argument("--controller-url")
    p.add_argument("--region-id")
    p.add_argument("--datacenter-id")
    p.add_argument("--name")
    p.add_argument("--port-range", metavar="START-END")
    p.add_argument("--port-protocol", choices=("tcp", "udp", "both"))
    source = p.add_mutually_exclusive_group()
    source.add_argument("--release-tag", help="GitHub Agent release tag; default: latest")
    source.add_argument("--package-file", help="local Linux Agent .tar.gz package for homologation")
    p.add_argument("--pairing-ttl", type=int, default=900)
    p.add_argument("--connect-timeout", type=int, default=10)
    p.add_argument("--bootstrap-timeout", type=int, default=900)
    p.add_argument("--heartbeat-timeout", type=int, default=180)
    p.add_argument("--concurrency", type=int, default=5, help="batch workers, 1-20; default: 5")
    p.add_argument("--json", action="store_true")
    return p


def _print_human(payload):
    print("Capivara Agent Deployment\n")
    for label, key in (("Host", "host"), ("SSH user", "ssh_user"), ("Authentication", "authentication"), ("Controller", "controller_id"), ("Controller URL", "controller_url"), ("Region", "region_id"), ("Datacenter", "datacenter_id"), ("Remote platform", "remote_platform"), ("Architecture", "remote_architecture"), ("Agent", "agent_id"), ("Node", "node_id"), ("Status", "agent_status"), ("Health", "health_status")):
        print(f"{label:<18}: {payload.get(key)}")
    print("Deployment        : completed")


def _single_args(args, target):
    values = vars(args).copy()
    values.update(
        host=target.host,
        ssh_user=target.ssh_user,
        ssh_port=target.ssh_port,
        platform=target.platform,
        name=target.name or args.name,
        password_file=target.password_file,
        identity_file=target.identity_file,
        region_id=target.region_id or args.region_id,
        datacenter_id=target.datacenter_id or args.datacenter_id,
    )
    return argparse.Namespace(**values)


def _targets(args):
    if bool(args.host) == bool(args.hosts_file):
        raise ValueError("use exactly one HOST or --hosts-file CSV")
    defaults = {
        "ssh_user": args.ssh_user,
        "ssh_port": args.ssh_port,
        "platform": args.platform,
        "password_file": args.password_file,
        "identity_file": args.identity_file,
        "region_id": args.region_id,
        "datacenter_id": args.datacenter_id,
    }
    if args.hosts_file:
        return load_csv_targets(args.hosts_file, defaults=defaults), True
    return [target_from_values(host=args.host, name=args.name, **defaults)], False


def _deploy_target(args, target):
    target_args = _single_args(args, target)
    try:
        payload = deploy(target_args)
        payload["name"] = target.name or payload.get("preconfiguration", {}).get("agent_name")
        payload["ok"] = True
        return payload
    except (AgentDeployError, ValueError, LookupError, OSError) as exc:
        return {
            "ok": False,
            "deployment": "failed",
            "host": target.host,
            "name": target.name,
            "ssh_user": target.ssh_user,
            "ssh_port": target.ssh_port,
            "platform": target.platform,
            "error": str(exc),
        }


def _run_batch(args, targets):
    workers = min(normalize_concurrency(args.concurrency), len(targets))
    results = [None] * len(targets)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cap-agent-deploy") as executor:
        futures = {executor.submit(_deploy_target, args, target): index for index, target in enumerate(targets)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    succeeded = sum(1 for item in results if item and item.get("ok"))
    return {
        "ok": succeeded == len(results),
        "deployment": "completed" if succeeded == len(results) else "partial",
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "targets": results,
    }


def _print_batch(payload):
    print("Capivara Agent Batch Deployment\n")
    for item in payload["targets"]:
        label = item.get("name") or item["host"]
        state = "ONLINE" if item.get("ok") else "FALHOU"
        detail = item.get("agent_id") or item.get("error") or ""
        print(f"{label:<24} {item['host']}:{item['ssh_port']:<5} {state:<7} {detail}")
    print(f"\nTotal: {payload['total']} · Instalados: {payload['succeeded']} · Falhas: {payload['failed']}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        targets, batch = _targets(args)
        if batch:
            payload = _run_batch(args, targets)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            else:
                _print_batch(payload)
            return 0 if payload["ok"] else 3
        payload = _deploy_target(args, targets[0])
        if not payload["ok"]:
            if args.json:
                print(json.dumps({"deployment": "failed", "error": payload["error"]}, ensure_ascii=False))
                return 2
            parser.exit(2, f"Erro: {payload['error']}\n")
        payload.pop("ok", None)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            _print_human(payload)
        return 0
    except (AgentDeployError, ValueError, LookupError, OSError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"deployment": "failed", "error": str(exc)}, ensure_ascii=False))
            return 2
        parser.exit(2, f"Erro: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())