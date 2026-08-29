#!/usr/bin/env python3
"""HTTP-safe service contract for remote Agent enrollment and heartbeat."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from agent_admin_repository import AgentAdminRepository
from agent_game_data_repository import AgentGameDataRepository
from agent_heartbeat_api import (
    AgentHostIdentityCollision,
    AgentHostIdentityRequired,
    record_agent_heartbeat,
)
from agent_installation_api import bind_installation_after_enrollment
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from agent_lifecycle_repository import AgentLifecycleRepository
from agent_identity_incident_repository import AgentIdentityIncidentRepository
from agent_link_incident_repository import AgentLinkIncidentRepository
from agent_pairing_api import enroll_remote_agent
from agent_pairing_repository import (
    AgentCredentialInvalid,
    AgentPairingRepository,
    PairingRegistrationConflict,
    PairingTokenConsumed,
    PairingTokenExpired,
    PairingTokenInvalid,
)
from agent_update_repository import AgentUpdateRepository
from deleted_backup_vault_repository import DeletedBackupVaultRepository
from instance_backup_clone_repository import InstanceBackupCloneRepository
from instance_provisioning_projection import project_agent_provisioning

ENROLL_PATH = "/api/agent/enroll"
HEARTBEAT_PATH = "/api/agent/heartbeat"
ROOT = Path(__file__).resolve().parents[1]
_LAST_VAULT_CLEANUP = 0.0
_LINK_CRITICAL_CODES = {
    "identity_incomplete",
    "not_enrolled",
    "credential_invalid",
    "credential_revoked",
    "fingerprint_mismatch",
    "controller_mismatch",
}


def dispatch_enroll(payload: dict[str, Any] | None, *, backend) -> tuple[int, dict[str, Any]]:
    try:
        result = enroll_remote_agent(backend, payload)
    except (PairingTokenInvalid, PairingTokenExpired, PairingTokenConsumed):
        return 401, {"error": "pairing_rejected", "message": "Pareamento inválido ou expirado."}
    except (PairingRegistrationConflict, ValueError):
        return 409, {"error": "pairing_conflict", "message": "Não foi possível registrar este Agent."}
    except Exception:
        return 500, {"error": "pairing_failed", "message": "Não foi possível concluir o pareamento."}
    tracking_bound = True
    try:
        bind_installation_after_enrollment(
            backend,
            pairing_token=str((payload or {}).get("pairing_token", "")),
            agent_id=str(result["agent_id"]),
        )
    except Exception:
        tracking_bound = False
    identity = dict(result.get("identity") or {})
    return 201, {
        "agent_id": result["agent_id"],
        "node_id": result["node_id"],
        "controller_id": result["controller_id"],
        "status": result["status"],
        "credential_id": identity["credential_id"],
        "credential_secret": identity["credential_secret"],
        "credential_type": identity["credential_type"],
        "fingerprint": identity["fingerprint"],
        "pairing_token_consumed": bool(result.get("pairing_token_consumed")),
        "installation_tracking_bound": tracking_bound,
    }


def _attach_update_state(result, body, *, agent_id, backend):
    try:
        updates = AgentUpdateRepository(backend)
        updates.initialize()
        update_state = updates.reconcile_after_heartbeat(
            agent_id,
            body.get("capivara_version"),
            result.get("health_status", "online"),
        )
        update_result = body.get("update_result") if isinstance(body.get("update_result"), dict) else None
        failed_rollout_id = str((update_result or {}).get("rollout_id") or "").strip()
        active_rollout_id = str(update_state.get("rollout_id") or "").strip()
        if (
            update_result
            and str(update_result.get("status", "")).lower() == "failed"
            and failed_rollout_id
            and failed_rollout_id == active_rollout_id
        ):
            update_state = updates.mark_failed(agent_id, str(update_result.get("error", "update failed"))[:2000])
            command = None
        else:
            command = updates.command_for_agent(agent_id)
            if command and update_state.get("update_status") == "planned":
                update_state = updates.mark_updating(agent_id)
            if command:
                result["update"] = command
        result["update_state"] = update_state
    except Exception:
        result["update_state"] = {"update_status": "unavailable"}


def _attach_provisioning_state(result, body, *, agent_id, backend):
    try:
        jobs = AgentInstanceProvisioningRepository(backend)
        jobs.initialize()
        reported = body.get("provisioning_result") if isinstance(body.get("provisioning_result"), dict) else None
        reported_state = jobs.apply_result(agent_id, reported) if reported else None
        command = jobs.command_for_agent(agent_id)
        command_state = None
        if command:
            command_state = jobs.mark_delivered(str(command["provisioning_id"]))
            result["provisioning_command"] = command
        effective_state = reported_state or command_state
        if effective_state:
            try:
                project_agent_provisioning(backend, effective_state)
            except Exception:
                pass
        result["provisioning_state"] = effective_state or {"status": "idle"}
    except Exception:
        result["provisioning_state"] = {"status": "unavailable"}


def _attach_game_data_state(result, body, *, agent_id, backend):
    try:
        jobs = AgentGameDataRepository(backend)
        jobs.initialize()
        reported = body.get("game_data_result") if isinstance(body.get("game_data_result"), dict) else None
        reported_state = jobs.apply_result(agent_id, reported) if reported else None
        command = jobs.command_for_agent(agent_id)
        command_state = None
        if command:
            command_state = jobs.mark_delivered(str(command["job_id"]))
            result["game_data_command"] = command
        result["game_data_state"] = reported_state or command_state or {"status": "idle"}
    except Exception:
        result["game_data_state"] = {"status": "unavailable"}


def _attach_instance_state(result, body, *, agent_id, backend):
    try:
        commands = AgentInstanceRuntimeRepository(backend)
        commands.initialize()
        reported = body.get("instance_result") if isinstance(body.get("instance_result"), dict) else None
        reported_state = commands.apply_result(agent_id, reported) if reported else None
        command = commands.command_for_agent(agent_id)
        command_state = None
        if command:
            command_state = commands.mark_delivered(str(command["command_id"]))
            result["instance_command"] = command
        result["instance_state"] = reported_state or command_state or {"status": "idle"}
    except Exception:
        result["instance_state"] = {"status": "unavailable"}


def _attach_doctor_state(result, body, *, agent_id, backend):
    """Exchange one fixed Doctor command/result without exposing a shell channel."""
    try:
        admin = AgentAdminRepository(backend)
        reported = body.get("doctor_result") if isinstance(body.get("doctor_result"), dict) else None
        reported_state = admin.apply_doctor_result(agent_id, reported) if reported else None
        command = admin.doctor_command_for_agent(agent_id)
        if command:
            result["doctor_command"] = command
        result["doctor_state"] = reported_state or admin.latest_doctor(agent_id) or {"status": "idle"}
    except Exception:
        result["doctor_state"] = {"status": "unavailable"}


def _doctor_link_recovery_ready(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict) or str(state.get("status") or "").lower() != "completed":
        return False
    report = state.get("result") if isinstance(state.get("result"), dict) else None
    if report is None:
        return False
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "").lower()
        code = str(finding.get("code") or "").lower()
        if severity == "critical" and code in _LINK_CRITICAL_CODES:
            return False
    return True


def _reconcile_link_incident(result, *, agent_id, backend):
    """Require a valid heartbeat plus Doctor confirmation before auto-resolve."""
    try:
        incidents = AgentLinkIncidentRepository(backend)
        active = incidents.active(agent_id)
        if active is None:
            return
        admin = AgentAdminRepository(backend)
        doctor = admin.latest_doctor(agent_id)
        if _doctor_link_recovery_ready(doctor):
            report = doctor.get("result") if isinstance(doctor, dict) else {}
            incidents.resolve(
                agent_id,
                recovery="authenticated_heartbeat_and_doctor",
                doctor_status=str((report or {}).get("status") or "healthy"),
            )
            result["link_incident"] = {"status": "resolved", "incident_id": active["id"]}
            return

        queued = admin.request_doctor(agent_id, requested_by="system:link-recovery")
        command = admin.doctor_command_for_agent(agent_id)
        if command:
            result["doctor_command"] = command
        result["doctor_state"] = admin.latest_doctor(agent_id) or queued
        result["link_incident"] = {
            "status": "recovering",
            "incident_id": active["id"],
            "action": "Executar Doctor",
        }
    except Exception:
        result["link_incident"] = {"status": "unavailable"}


def _attach_backup_clone_state(result, *, agent_id, backend):
    global _LAST_VAULT_CLEANUP
    try:
        now = time.monotonic()
        if now - _LAST_VAULT_CLEANUP >= 300:
            DeletedBackupVaultRepository(backend, ROOT).cleanup_expired()
            _LAST_VAULT_CLEANUP = now
        clones = InstanceBackupCloneRepository(backend, ROOT)
        clones.initialize()
        result["backup_clone_states"] = clones.reconcile_for_agent(agent_id)
    except Exception:
        result["backup_clone_states"] = []


def dispatch_heartbeat(payload: dict[str, Any] | None, *, headers, backend) -> tuple[int, dict[str, Any]]:
    credential_id = str(headers.get("X-Capivara-Agent-Credential", "")).strip()
    credential_secret = str(headers.get("X-Capivara-Agent-Secret", "")).strip()
    fingerprint = str(headers.get("X-Capivara-Agent-Fingerprint", "")).strip() or None
    body = payload if isinstance(payload, dict) else {}
    try:
        identity = AgentPairingRepository(backend).authenticate(
            credential_id=credential_id,
            credential_secret=credential_secret,
            fingerprint=fingerprint,
        )
        agent_id = identity["agent_id"]
        result = record_agent_heartbeat(agent_id, body, backend=backend, root=ROOT)
        status = str(identity.get("status", "")).strip().lower()
        if status == "pairing":
            status = AgentLifecycleRepository(backend).transition(agent_id, "active").target
        result["status"] = status
        _attach_update_state(result, body, agent_id=agent_id, backend=backend)
        _attach_provisioning_state(result, body, agent_id=agent_id, backend=backend)
        provisioning_state = result.get("provisioning_state") if isinstance(result.get("provisioning_state"), dict) else {}
        if str(provisioning_state.get("status") or "").lower() in {"queued", "delivered", "running"}:
            result["game_data_state"] = {"status": "deferred", "reason": "instance_provisioning_active"}
        else:
            _attach_game_data_state(result, body, agent_id=agent_id, backend=backend)
        _attach_instance_state(result, body, agent_id=agent_id, backend=backend)
        _attach_doctor_state(result, body, agent_id=agent_id, backend=backend)
        _reconcile_link_incident(result, agent_id=agent_id, backend=backend)
        _attach_backup_clone_state(result, agent_id=agent_id, backend=backend)
    except AgentHostIdentityCollision as exc:
        try:
            AgentIdentityIncidentRepository(backend).open_collision(
                exc.agent_id,
                expected_identity=exc.expected,
                presented_identity=exc.presented,
            )
        except Exception:
            pass
        return 409, {
            "error": "agent_identity_collision",
            "message": (
                "A identidade deste Agent já está vinculada a outro host."
            ),
        }
    except AgentHostIdentityRequired as exc:
        try:
            AgentIdentityIncidentRepository(backend).open_collision(
                exc.agent_id,
            )
        except Exception:
            pass
        return 409, {
            "error": "agent_host_identity_required",
            "message": (
                "Este Agent precisa informar sua identidade física."
            ),
        }
    except AgentCredentialInvalid:
        try:
            incidents = AgentLinkIncidentRepository(backend)
            failed_agent_id = incidents.identify_agent_from_credential_reference(
                credential_id,
                fingerprint=fingerprint,
            )
            if failed_agent_id:
                incidents.open(
                    failed_agent_id,
                    cause="credential_invalid",
                    recommended_action="Revincular Agent",
                    message="A credencial apresentada pelo Agent foi rejeitada. Revincule o Agent para restaurar a confiança.",
                )
        except Exception:
            pass
        return 401, {"error": "agent_authentication_failed", "message": "Identidade do Agent inválida."}
    except Exception:
        return 500, {"error": "heartbeat_failed", "message": "Não foi possível registrar o heartbeat."}
    return 200, result
