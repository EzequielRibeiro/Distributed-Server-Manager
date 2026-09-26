"""Transactional optional Votifier port lifecycle for stopped Hybrid instances.

A remote Agent may opt in during provisioning; post-provision updates require
an Agent-side network reconfiguration protocol and are rejected until supported.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from customer_instance_creation import runtime_definition
from hybrid_runtime_port_backfill import reconcile_hybrid_runtime_ports
from instance_network import occupied_ports_provider_for_backend
from instance_workspace_repository import InstanceWorkspaceRepository


class OptionalPortError(ValueError):
    pass


def _hybrid_spec(root: Path, instance_id: str, agent_id: str) -> Path:
    local_agent_path = Path(root) / "runtime" / "hybrid-agent-state" / "agent.json"
    try:
        local_agent = json.loads(local_agent_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OptionalPortError("A identificação do Agent híbrido local não está disponível.") from exc
    if not isinstance(local_agent, dict) or local_agent.get("agent_id") != agent_id:
        raise OptionalPortError("Alterações posteriores exigem o Agent híbrido local correto.")
    path = Path(root) / "runtime" / "hybrid-agent-state" / "instances" / f"{instance_id}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OptionalPortError("Atualização posterior disponível somente em Agent híbrido sincronizado.") from exc
    if not isinstance(record, dict) or str(record.get("agent_id") or "") != agent_id:
        raise OptionalPortError("O RuntimeSpec não pertence ao Agent selecionado.")
    return path


def _stopped(instance_id: str) -> None:
    result = subprocess.run(
        ["systemctl", "show", f"capivara-instance-{instance_id}.service",
         "--property=ActiveState", "--property=LoadState", "--no-pager"],
        capture_output=True, text=True, timeout=6, check=False,
    )
    state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if result.returncode != 0 or state.get("LoadState") != "loaded" or state.get("ActiveState") != "inactive":
        raise OptionalPortError("O serviço precisa estar carregado e completamente parado para alterar a porta Votifier.")


def _metadata(raw) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        raise OptionalPortError("Metadados da instância inválidos.")
    if not isinstance(value, dict):
        raise OptionalPortError("Metadados da instância inválidos.")
    return value


def _catalog_role(root: Path, game: str, runtime: str, *, enable: bool) -> dict:
    definition = runtime_definition(root, game, runtime)
    network = definition.get("network") or {}
    candidates = network.get("on_demand_ports") or []
    role = next((item for item in candidates if item.get("name") == "votifier"), None)
    if enable and (not role or role.get("protocol") != "tcp"):
        raise OptionalPortError("Este runtime não oferece integração Votifier.")
    if not role:
        role = next((item for item in network.get("legacy_reservations") or []
                     if item.get("name") == "votifier"), None)
    if not role:
        raise OptionalPortError("Este runtime não possui reserva Votifier.")
    return role


def _choose_tcp(session, ph, provider, agent_id: str, node_id: str, preferred: int) -> int:
    rows = session.execute(
        "SELECT protocol,start_port,end_port FROM agent_port_ranges "
        f"WHERE agent_id={ph} AND status='active' ORDER BY start_port",
        (agent_id,),
    ).fetchall()
    ranges = [
        (int(row["start_port"]), int(row["end_port"]))
        for row in rows if row["protocol"] == "tcp"
    ]
    if not ranges:
        raise OptionalPortError("O Agent não possui faixa TCP ativa.")
    reserved_rows = session.execute(
        f"SELECT protocol,port FROM instance_ports WHERE node_id={ph}", (node_id,),
    ).fetchall()
    unavailable = {int(row["port"]) for row in reserved_rows}
    # Always inspect both protocols: numeric ownership is node-wide.
    for low, high in ranges:
        for protocol in ("tcp", "udp"):
            unavailable.update(int(p) for p in provider(
                agent_id, node_id, protocol, low, high
            ))
    if preferred > 0 and any(lo <= preferred <= hi for lo, hi in ranges) and preferred not in unavailable:
        return preferred
    for low, high in ranges:
        for port in range(low, high + 1):
            if port not in unavailable:
                return port
    raise OptionalPortError("Não existe porta TCP livre no Agent para o Votifier.")


def _sync(backend, root: Path, agent_id: str, instance_id: str) -> None:
    state = reconcile_hybrid_runtime_ports(
        backend, root, agent_id, only_instance_id=instance_id,
    )
    if int(state.get("instances") or 0) != 1:
        raise RuntimeError("A sincronização do RuntimeSpec não confirmou a instância.")


def _read_synced(path: Path, *, enabled: bool, port: int | None = None) -> bool:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    binding = (record.get("ports") or {}).get("votifier")
    return (isinstance(binding, dict)
            and str(binding.get("protocol") or "").lower() == "tcp"
            and int(binding.get("port") or 0) == port) if enabled else binding is None


def set_votifier(backend, root: Path, instance_id: str, *, enabled: bool) -> dict:
    """Idempotent opt-in/out, serialized against numeric port owners."""
    if not isinstance(enabled, bool):
        raise OptionalPortError("enabled deve ser booleano.")
    root = Path(root)
    repo = InstanceWorkspaceRepository(backend)
    context = repo.instance_context(instance_id)
    agent_id = str(context.get("agent_id") or "")
    node_id = str(context.get("node_id") or "")
    role = _catalog_role(root, context.get("game_id"), context.get("runtime_id"), enable=enabled)
    path = _hybrid_spec(root, instance_id, agent_id)
    ph = repo.dialect.placeholder

    # Never mutate an Agent runtime record while its game process is active,
    # including retries after an interrupted prior attempt.
    _stopped(instance_id)

    with repo.session(transaction=True) as session:
        lock = " FOR UPDATE" if repo.backend.name in {"postgresql", "mysql"} else ""
        row = session.execute(
            f"SELECT id,node_id,agent_id,status,metadata_json FROM instances WHERE id={ph}{lock}",
            (instance_id,),
        ).fetchone()
        if row is None or row["agent_id"] != agent_id or row["node_id"] != node_id:
            raise OptionalPortError("Instância/Agent alterados durante a solicitação.")
        session.execute(f"SELECT id FROM nodes WHERE id={ph}{lock}", (node_id,)).fetchone()
        state = str(row.get("status") or "").lower()
        current = session.execute(
            f"SELECT port FROM instance_ports WHERE instance_id={ph} AND name='votifier'",
            (instance_id,),
        ).fetchone()
        data = _metadata(row["metadata_json"])
        network = dict(data.get("network") or {})
        ports = dict(network.get("ports") or {})
        if enabled:
            if current is None:
                if state not in {"stopped", "offline"}:
                    raise OptionalPortError("A instância precisa estar parada.")
                # Check the systemd state under the same node lock as allocation.
                _stopped(instance_id)
                game_row = session.execute(
                    f"SELECT port FROM instance_ports WHERE instance_id={ph} AND name='game'",
                    (instance_id,),
                ).fetchone()
                preferred = int(game_row["port"]) + int(role.get("offset") or 0) if game_row else 0
                chosen = _choose_tcp(
                    session, ph, occupied_ports_provider_for_backend(backend),
                    agent_id, node_id, preferred,
                )
                session.execute(
                    "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port,bind_address) "
                    f"VALUES ({repo.dialect.parameters(6)})",
                    (instance_id, node_id, "votifier", "tcp", chosen, "0.0.0.0"),
                )
            else:
                chosen = int(current["port"])
            ports["votifier"] = chosen
            data.pop("network_optional_pending_drop", None)
        else:
            if current is None:
                return {"status": "disabled", "port": None, "changed": False}
            if state not in {"stopped", "offline"}:
                raise OptionalPortError("A instância precisa estar parada.")
            _stopped(instance_id)
            data["network_optional_pending_drop"] = ["votifier"]
            chosen = int(current["port"])
        network["ports"] = ports
        data["network"] = network
        session.execute(
            f"UPDATE instances SET metadata_json={ph} WHERE id={ph}",
            (json.dumps(data, ensure_ascii=False), instance_id),
        )

    # Controller reservation commits first; on failure it stays owned and a
    # subsequent retry/Hybrid heartbeat can finish without port reuse.
    try:
        _stopped(instance_id)
        _sync(backend, root, agent_id, instance_id)
        if not _read_synced(path, enabled=enabled, port=chosen if enabled else None):
            raise RuntimeError("Os bindings do Agent ainda não estão sincronizados.")
    except Exception as exc:
        return {"status": "pending_sync", "port": chosen,
                "message": str(exc)[:250]}

    if enabled:
        return {"status": "enabled", "port": chosen}

    # Release only AFTER the stopped Agent record no longer references it.
    with repo.session(transaction=True) as session:
        lock = " FOR UPDATE" if repo.backend.name in {"postgresql", "mysql"} else ""
        row = session.execute(
            f"SELECT id,node_id,agent_id,status,metadata_json FROM instances WHERE id={ph}{lock}",
            (instance_id,),
        ).fetchone()
        session.execute(f"SELECT id FROM nodes WHERE id={ph}{lock}", (node_id,)).fetchone()
        if row is None or row["agent_id"] != agent_id or row["node_id"] != node_id:
            raise OptionalPortError("Instância alterada durante a desativação.")
        data = _metadata(row["metadata_json"])
        if "votifier" not in (data.get("network_optional_pending_drop") or []):
            return {"status": "pending_sync", "port": chosen}
        if str(row.get("status") or "").lower() not in {"stopped", "offline"}:
            return {"status": "pending_sync", "port": chosen}
        _stopped(instance_id)
        if not _read_synced(path, enabled=False):
            return {"status": "pending_sync", "port": chosen}
        # A disconnected plugin must not still own an active socket.
        if chosen in occupied_ports_provider_for_backend(backend)(
            agent_id, node_id, "tcp", chosen, chosen
        ):
            raise OptionalPortError("A porta continua ocupada e não pode ser liberada.")
        session.execute(
            f"DELETE FROM instance_ports WHERE instance_id={ph} AND name='votifier'",
            (instance_id,),
        )
        network = dict(data.get("network") or {})
        ports = dict(network.get("ports") or {})
        ports.pop("votifier", None)
        network["ports"] = ports
        data["network"] = network
        data.pop("network_optional_pending_drop", None)
        session.execute(
            f"UPDATE instances SET metadata_json={ph} WHERE id={ph}",
            (json.dumps(data, ensure_ascii=False), instance_id),
        )
    return {"status": "disabled", "port": None}
