#!/usr/bin/env python3
"""Administrative CLI for bootstrapping a Linux Agent over SSH."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
for candidate in (ROOT_DIR, ROOT_DIR / "core", ROOT_DIR / "database"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from agent_pairing_repository import AgentPairingRepository
from agent_ssh_deploy import (
    AgentDeployError,
    SSHDeployOptions,
    bootstrap_agent,
    preflight_ssh,
    remote_agent_present,
    wait_for_agent_online,
)
from alert_repository import AlertSession, dialect_for_backend
from runtime_backend import backend_from_environment


def _active_controller_id(backend, requested: str | None) -> str:
    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            if requested:
                row = session.execute(
                    f"SELECT id,status FROM controllers WHERE id={ph}",
                    (str(requested).strip(),),
                ).fetchone()
                if row is None:
                    raise AgentDeployError(f"Controller not found: {requested}")
                if str(row["status"]).lower() != "active":
                    raise AgentDeployError("Controller must be active")
                return str(row["id"])

            rows = session.execute(
                "SELECT id FROM controllers WHERE status='active' ORDER BY id"
            ).fetchall()
        finally:
            session.close()
    if not rows:
        raise AgentDeployError("no active Controller identity found")
    if len(rows) > 1:
        raise AgentDeployError("multiple active Controllers found; use --controller-id")
    return str(rows[0]["id"])


def _source_address_for_host(host: str) -> str:
    """Resolve the local address the kernel would use to reach HOST."""
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
            continue
        finally:
            sock.close()
    raise AgentDeployError("unable to determine Controller address reachable by Agent")


def _controller_url(host: str, requested: str | None) -> str:
    explicit = str(requested or "").strip() or str(os.environ.get("DSM_CONTROLLER_URL", "")).strip()
    if explicit:
        if not explicit.startswith(("http://", "https://")):
            raise AgentDeployError("controller URL must use http:// or https://")
        return explicit.rstrip("/")
    address = _source_address_for_host(host)
    if ":" in address:
        address = f"[{address}]"
    port = int(os.environ.get("DSM_DASHBOARD_PORT", "8080") or "8080")
    return f"http://{address}:{port}"


def _annotate_pairing(
    backend,
    *,
    token_id: str,
    region_id: str | None,
    datacenter_id: str | None,
) -> None:
    """Best-effort metadata compatible with the existing installation workflow."""
    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder
    with backend.transaction() as connection:
        session = AlertSession(backend, connection)
        try:
            columns = {str(row["name"]) for row in session.execute("PRAGMA table_info(agent_pairing_tokens)").fetchall()} if dialect.name == "sqlite" else set()
            assignments: list[str] = []
            values: list[Any] = []
            for column, value in (
                ("platform", "linux"),
                ("install_method", "ssh"),
                ("region_id", region_id),
                ("datacenter_id", datacenter_id),
            ):
                if columns and column not in columns:
                    continue
                if value is None and column in {"region_id", "datacenter_id"}:
                    continue
                assignments.append(f"{column}={ph}")
                values.append(value)
            if assignments:
                values.append(token_id)
                session.execute(
                    "UPDATE agent_pairing_tokens SET " + ",".join(assignments) + f" WHERE id={ph}",
                    tuple(values),
                )
        finally:
            session.close()


def _status_reader(backend, token_id: str):
    dialect = dialect_for_backend(backend)
    ph = dialect.placeholder

    def read() -> dict[str, Any]:
        with backend.connect() as connection:
            session = AlertSession(backend, connection)
            try:
                row = session.execute(
                    "SELECT agent_id,consumed_at FROM agent_pairing_tokens " + f"WHERE id={ph}",
                    (token_id,),
                ).fetchone()
                if row is None:
                    raise AgentDeployError("pairing record disappeared during deployment")
                agent_id = str(row["agent_id"]) if row["agent_id"] else None
                payload: dict[str, Any] = {
                    "agent_id": agent_id,
                    "pairing_consumed": bool(row["consumed_at"]),
                    "agent_status": None,
                    "health_status": None,
                }
                if not agent_id:
                    return payload
                agent = session.execute(
                    f"SELECT status,node_id,name FROM agents WHERE id={ph}",
                    (agent_id,),
                ).fetchone()
                runtime = session.execute(
                    f"SELECT health_status,last_seen,hostname,address FROM agent_runtime_inventory WHERE agent_id={ph}",
                    (agent_id,),
                ).fetchone()
                if agent is not None:
                    payload.update(
                        agent_status=str(agent["status"]),
                        node_id=str(agent["node_id"]),
                        name=str(agent["name"]),
                    )
                if runtime is not None:
                    payload.update(
                        health_status=str(runtime["health_status"] or ""),
                        last_seen=runtime["last_seen"],
                        hostname=runtime["hostname"],
                        address=runtime["address"],
                    )
                return payload
            finally:
                session.close()

    return read


def deploy(args: argparse.Namespace) -> dict[str, Any]:
    backend = backend_from_environment()
    try:
        backend.initialize()
        options = SSHDeployOptions(
            host=args.host,
            ssh_user=args.ssh_user,
            ssh_port=args.ssh_port,
            identity_file=args.identity_file,
            connect_timeout=args.connect_timeout,
        )
        controller_id = _active_controller_id(backend, args.controller_id)
        controller_url = _controller_url(args.host, args.controller_url)

        preflight = preflight_ssh(options)
        if remote_agent_present(options):
            raise AgentDeployError(
                "Capivara Agent installation already detected on remote host; refusing automatic reinstall"
            )

        issued = AgentPairingRepository(backend).issue_token(
            controller_id=controller_id,
            created_by=os.environ.get("USER") or None,
            ttl_seconds=args.pairing_ttl,
        )
        _annotate_pairing(
            backend,
            token_id=issued.token_id,
            region_id=args.region_id,
            datacenter_id=args.datacenter_id,
        )

        bootstrap_agent(
            options,
            controller_url=controller_url,
            pairing_token=issued.token,
            timeout=args.bootstrap_timeout,
        )
        online = wait_for_agent_online(
            _status_reader(backend, issued.token_id),
            timeout=args.heartbeat_timeout,
        )
        return {
            "deployment": "completed",
            "host": args.host,
            "ssh_user": args.ssh_user,
            "ssh_port": args.ssh_port,
            "controller_id": controller_id,
            "controller_url": controller_url,
            "remote_platform": preflight.get("platform"),
            "remote_architecture": preflight.get("architecture"),
            "agent_id": online.get("agent_id"),
            "node_id": online.get("node_id"),
            "agent_status": online.get("agent_status"),
            "health_status": online.get("health_status"),
            "last_seen": online.get("last_seen"),
        }
    finally:
        backend.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy a Capivara Linux Agent over SSH")
    parser.add_argument("host", help="remote Agent host (IPv4, IPv6 or hostname)")
    parser.add_argument("--ssh-user", required=True, help="SSH bootstrap user")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--identity-file")
    parser.add_argument("--controller-id")
    parser.add_argument("--controller-url")
    parser.add_argument("--region-id")
    parser.add_argument("--datacenter-id")
    parser.add_argument("--pairing-ttl", type=int, default=900)
    parser.add_argument("--connect-timeout", type=int, default=10)
    parser.add_argument("--bootstrap-timeout", type=int, default=900)
    parser.add_argument("--heartbeat-timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    return parser


def _print_human(payload: dict[str, Any]) -> None:
    print("Capivara Agent Deployment")
    print()
    fields = (
        ("Host", payload.get("host")),
        ("SSH user", payload.get("ssh_user")),
        ("Controller", payload.get("controller_id")),
        ("Controller URL", payload.get("controller_url")),
        ("Remote platform", payload.get("remote_platform")),
        ("Architecture", payload.get("remote_architecture")),
        ("Agent", payload.get("agent_id")),
        ("Node", payload.get("node_id")),
        ("Status", payload.get("agent_status")),
        ("Health", payload.get("health_status")),
    )
    for label, value in fields:
        print(f"{label:<18}: {value}")
    print("Deployment        : completed")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = deploy(args)
    except (AgentDeployError, ValueError, LookupError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"deployment": "failed", "error": str(exc)}, ensure_ascii=False))
            return 2
        parser.exit(2, f"Erro: {exc}\n")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
