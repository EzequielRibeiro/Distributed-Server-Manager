#!/usr/bin/env python3
"""Administrative Agent maintenance and secure credential relink HTTP composition."""
from __future__ import annotations

from pathlib import Path
import uuid
from urllib.parse import parse_qs, urlparse

from agent_admin_repository import AgentAdminRepository
from agent_pairing_repository import (
    AgentCredentialInvalid,
    AgentPairingRepository,
    PairingTokenConsumed,
    PairingTokenExpired,
    PairingTokenInvalid,
)
from agent_relink_repository import AgentRelinkRepository
from configuration_repository import ConfigurationRepository
from instance_storage_pool_migration_repository import InstanceStoragePoolMigrationRepository
from universal_event_repository import UniversalEventRepository

DETAIL_PATH = "/api/admin/agent"
RENAME_PATH = "/api/admin/agent/rename"
REMOVE_PATH = "/api/admin/agent/remove"
STORAGE_PATH = "/api/admin/agent/storage"
STORAGE_MIGRATE_PATH = "/api/admin/agent/storage/migrate"
INSTANCE_STORAGE_POOL_MIGRATION_PATH = "/api/admin/instance/storage-pool-migrate"
DOCTOR_PATH = "/api/admin/agent/doctor"
RELINK_PREPARE_PATH = "/api/admin/agent/relink/prepare"
CREDENTIAL_ROTATE_PATH = "/api/admin/agent/credential-rotate"
REMOTE_RELINK_PATH = "/api/agent/relink"
_STORAGE_NAMESPACE = "capivara.agent.storage"
_DEFAULT_STORAGE_ROOT = "/var/lib/capivara-instances"


def _backend(legacy):
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _role(user) -> str:
    return str((user or {}).get("role") or "").strip().lower()


def _authorize(user, detail: dict, *, doctor: bool = False) -> None:
    role = _role(user)
    if role == "admin":
        return
    if role == "controller" and str(user.get("scope_id") or "") == str(detail.get("controller_id") or ""):
        return
    if doctor and role == "operator":
        return
    raise PermissionError("Agent administration access denied")


def _storage_root(value) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("instance_storage_root is required")
    path = Path(text)
    if not path.is_absolute():
        raise ValueError("instance_storage_root must be an absolute path")
    resolved = path.resolve(strict=False)
    if resolved == Path("/"):
        raise ValueError("instance_storage_root cannot be filesystem root")
    return str(resolved)


def _storage_detail(backend, agent_id: str) -> dict:
    repo = ConfigurationRepository(backend)
    repo.initialize()
    configured = repo.get(scope_type="agent", scope_id=agent_id, namespace=_STORAGE_NAMESPACE)
    root = _DEFAULT_STORAGE_ROOT
    revision = None
    checksum = None
    migration_requested = False
    if configured:
        value = configured.get("value") if isinstance(configured.get("value"), dict) else {}
        root = str(value.get("instance_storage_root") or _DEFAULT_STORAGE_ROOT)
        migration_requested = bool(value.get("migrate_existing"))
        revision = configured.get("revision")
        checksum = configured.get("checksum")
    return {
        "instance_storage_root": root,
        "source": "managed" if configured else "default",
        "revision": revision,
        "checksum": checksum,
        "migration_requested": migration_requested,
        "note": "Mudanças com instâncias existentes exigem migração explícita; o diretório antigo é preservado para rollback.",
    }


def _publish(backend, *, event_type: str, agent_id: str, actor: str, data: dict) -> None:
    try:
        UniversalEventRepository(backend).publish(
            {
                "event_id": str(uuid.uuid4()),
                "schema_version": 1,
                "event_type": event_type,
                "source": "dashboard.agent-admin",
                "source_id": agent_id,
                "severity": "info",
                "agent_id": agent_id,
                "actor_type": "user",
                "actor_id": actor,
                "data": data,
            }
        )
    except Exception:
        pass


def install_agent_administration(legacy, authenticate) -> None:
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def authenticated(self):
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return None
        return user

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path not in {DETAIL_PATH, DOCTOR_PATH, INSTANCE_STORAGE_POOL_MIGRATION_PATH}:
            return previous_get(self)
        user = authenticated(self)
        if user is None:
            return
        values = parse_qs(parsed.query or "")
        try:
            backend = _backend(legacy)
            if parsed.path == INSTANCE_STORAGE_POOL_MIGRATION_PATH:
                migration_id = str((values.get("migration_id") or [""])[0]).strip()
                if not migration_id:
                    raise ValueError("migration_id is required")
                migrations = InstanceStoragePoolMigrationRepository(backend)
                migrations.initialize()
                state = migrations.snapshot(migration_id)
                request = state.get("request") if isinstance(state.get("request"), dict) else {}
                agent_id = str(request.get("agent_id") or "").strip()
                detail = AgentAdminRepository(backend).detail(agent_id)
                _authorize(user, detail)
                self.send_json(200, {"migration": state})
                return

            agent_id = str((values.get("agent_id") or [""])[0]).strip()
            repo = AgentAdminRepository(backend)
            detail = repo.detail(agent_id)
            _authorize(user, detail, doctor=parsed.path == DOCTOR_PATH)
            if parsed.path == DOCTOR_PATH:
                self.send_json(200, {"agent_id": agent_id, "doctor": repo.latest_doctor(agent_id)})
            else:
                detail["storage"] = _storage_detail(backend, agent_id)
                self.send_json(200, {"agent": detail})
        except PermissionError as exc:
            self.send_json(403, {"error": "forbidden", "message": str(exc)})
        except (ValueError, LookupError, KeyError) as exc:
            self.send_json(404 if isinstance(exc, (LookupError, KeyError)) else 400, {"error": "invalid_request", "message": str(exc)})
        except Exception:
            self.send_json(500, {"error": "agent_admin_failed", "message": "Falha ao consultar o Agent."})

    def do_post(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == REMOTE_RELINK_PATH:
            try:
                payload = self.read_json_body()
                identity = AgentRelinkRepository(_backend(legacy)).relink(
                    pairing_token=str((payload or {}).get("pairing_token") or ""),
                    agent_id=str((payload or {}).get("agent_id") or ""),
                    node_id=str((payload or {}).get("node_id") or ""),
                    fingerprint=str((payload or {}).get("fingerprint") or ""),
                )
                self.send_json(200, {"agent_id": identity.agent_id, "node_id": identity.node_id, "controller_id": identity.controller_id, "status": identity.status, "credential_id": identity.credential_id, "credential_secret": identity.credential_secret, "credential_type": identity.credential_type, "fingerprint": identity.fingerprint})
            except (PairingTokenInvalid, PairingTokenExpired, PairingTokenConsumed, AgentCredentialInvalid):
                self.send_json(401, {"error": "relink_rejected", "message": "Token ou identidade do Agent inválidos."})
            except LookupError:
                self.send_json(404, {"error": "agent_not_found", "message": "Agent não encontrado."})
            except ValueError as exc:
                self.send_json(400, {"error": "invalid_request", "message": str(exc)})
            except Exception:
                self.send_json(500, {"error": "relink_failed", "message": "Não foi possível revincular o Agent."})
            return

        if path not in {RENAME_PATH, REMOVE_PATH, STORAGE_PATH, STORAGE_MIGRATE_PATH, INSTANCE_STORAGE_POOL_MIGRATION_PATH, DOCTOR_PATH, RELINK_PREPARE_PATH, CREDENTIAL_ROTATE_PATH}:
            return previous_post(self)
        user = authenticated(self)
        if user is None:
            return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."})
            return
        try:
            backend = _backend(legacy)
            actor = str(user.get("username") or "system")

            if path == INSTANCE_STORAGE_POOL_MIGRATION_PATH:
                if _role(user) == "operator":
                    raise PermissionError("operator is read-only")
                instance_id = str((payload or {}).get("instance_id") or "").strip()
                target_pool_id = str((payload or {}).get("target_storage_pool_id") or "").strip()
                migrations = InstanceStoragePoolMigrationRepository(backend)
                migrations.initialize()
                owner_agent_id = migrations.agent_for_instance(instance_id)
                detail = AgentAdminRepository(backend).detail(owner_agent_id)
                _authorize(user, detail)
                state = migrations.enqueue(
                    instance_id=instance_id,
                    target_storage_pool_id=target_pool_id,
                    requested_by=actor,
                )
                self.send_json(202, {"migration": state})
                return

            agent_id = str((payload or {}).get("agent_id") or "").strip()
            repo = AgentAdminRepository(backend)
            detail = repo.detail(agent_id)
            _authorize(user, detail, doctor=path == DOCTOR_PATH)

            if path == REMOVE_PATH:
                if _role(user) != "admin":
                    raise PermissionError("Somente administradores podem remover Agents")
                result = repo.remove(agent_id, confirmation=str((payload or {}).get("confirmation") or ""), actor=actor)
                _publish(backend, event_type="AGENT_REMOVED", agent_id=agent_id, actor=actor, data={"node_id": result["node_id"], "name": result["name"], "controller_id": result["controller_id"]})
                self.send_json(200, result)
                return

            if path == RENAME_PATH:
                if _role(user) == "operator": raise PermissionError("operator is read-only")
                result = repo.rename(agent_id, str((payload or {}).get("name") or ""), actor=actor)
                _publish(backend, event_type="AGENT_ADMIN_UPDATED", agent_id=agent_id, actor=actor, data={"field": "name", "name": result["name"]})
                self.send_json(200, result); return

            if path in {STORAGE_PATH, STORAGE_MIGRATE_PATH}:
                if _role(user) == "operator": raise PermissionError("operator is read-only")
                root = _storage_root((payload or {}).get("instance_storage_root"))
                migrate = path == STORAGE_MIGRATE_PATH
                configurations = ConfigurationRepository(backend); configurations.initialize()
                stored = configurations.put({"scope_type": "agent", "scope_id": agent_id, "namespace": _STORAGE_NAMESPACE, "value": {"instance_storage_root": root, "migrate_existing": migrate}}, updated_by=actor)
                _publish(backend, event_type="AGENT_INSTANCE_STORAGE_MIGRATION_REQUESTED" if migrate else "AGENT_INSTANCE_STORAGE_ROOT_REQUESTED", agent_id=agent_id, actor=actor, data={"instance_storage_root": root, "migrate_existing": migrate, "changed": bool(stored.get("changed"))})
                self.send_json(202, {"agent_id": agent_id, "storage": _storage_detail(backend, agent_id), "changed": bool(stored.get("changed"))}); return

            if path == DOCTOR_PATH:
                result = repo.request_doctor(agent_id, requested_by=actor)
                _publish(backend, event_type="AGENT_DOCTOR_REQUESTED", agent_id=agent_id, actor=actor, data={"request_id": result["request_id"]})
                self.send_json(202, {"agent_id": agent_id, "doctor": result}); return

            if _role(user) == "operator": raise PermissionError("operator cannot rotate Agent credentials")
            ttl = int((payload or {}).get("ttl_seconds") or 900)
            issued = AgentPairingRepository(backend).issue_token(controller_id=str(detail["controller_id"]), created_by=actor, ttl_seconds=ttl)
            state = repo.record_relink_prepared(agent_id, token_id=issued.token_id, expires_at=issued.expires_at, actor=actor)
            event_type = "AGENT_CREDENTIAL_ROTATION_PREPARED" if path == CREDENTIAL_ROTATE_PATH else "AGENT_RELINK_PREPARED"
            _publish(backend, event_type=event_type, agent_id=agent_id, actor=actor, data={"token_id": issued.token_id, "expires_at": issued.expires_at})
            self.send_json(201, {"agent_id": agent_id, "controller_id": detail["controller_id"], "node_id": detail["node_id"], "fingerprint": detail.get("fingerprint"), "pairing_token": issued.token, "token_id": issued.token_id, "expires_at": issued.expires_at, "state": state, "command": "sudo -u capivara-agent python3 /opt/capivara-agent/runtime/relink_cli.py --token '<TOKEN>' && sudo systemctl restart capivara-agent.service", "warning": "O token é exibido uma única vez. Não registre o token nem o novo secret em logs."})
        except PermissionError as exc:
            self.send_json(403, {"error": "forbidden", "message": str(exc)})
        except (LookupError, KeyError) as exc:
            self.send_json(404, {"error": "not_found", "message": str(exc)})
        except (ValueError, TypeError) as exc:
            self.send_json(400, {"error": "invalid_request", "message": str(exc)})
        except Exception:
            self.send_json(500, {"error": "agent_admin_failed", "message": "Falha na operação administrativa do Agent."})

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = ["INSTANCE_STORAGE_POOL_MIGRATION_PATH", "install_agent_administration"]
