from __future__ import annotations

from typing import FrozenSet


EVENT_TYPES: FrozenSet[str] = frozenset(
    {
        # Agents
        "AGENT_ENROLLMENT_REQUESTED",
        "AGENT_ENROLLED",
        "AGENT_PAIRING_STARTED",
        "AGENT_PAIRING_FAILED",
        "AGENT_ONLINE",
        "AGENT_OFFLINE",
        "AGENT_DISABLED",
        "AGENT_REJECTED",
        "AGENT_HEARTBEAT_LOST",
        "AGENT_HEARTBEAT_RESTORED",
        "AGENT_UPDATE_AVAILABLE",
        "AGENT_UPDATE_STARTED",
        "AGENT_UPDATE_COMPLETED",
        "AGENT_UPDATE_FAILED",
        # Placement
        "PLACEMENT_REQUESTED",
        "PLACEMENT_SELECTED",
        "PLACEMENT_UNAVAILABLE",
        "PLACEMENT_REJECTED",
        "PLACEMENT_RECONCILED",
        # Instances
        "INSTANCE_CREATE_REQUESTED",
        "INSTANCE_CREATED",
        "INSTANCE_INSTALL_STARTED",
        "INSTANCE_INSTALL_PROGRESS",
        "INSTANCE_INSTALL_COMPLETED",
        "INSTANCE_INSTALL_FAILED",
        "INSTANCE_START_REQUESTED",
        "INSTANCE_STARTED",
        "INSTANCE_START_FAILED",
        "INSTANCE_STOP_REQUESTED",
        "INSTANCE_STOPPED",
        "INSTANCE_STOP_FAILED",
        "INSTANCE_RESTART_REQUESTED",
        "INSTANCE_RESTARTED",
        "INSTANCE_FAILED",
        "INSTANCE_REMOVED",
        # Network
        "PORT_RESERVED",
        "PORT_RELEASED",
        "PORT_CONFLICT",
        "PORT_RANGE_EXHAUSTED",
        # Backup
        "BACKUP_REQUESTED",
        "BACKUP_STARTED",
        "BACKUP_CREATED",
        "BACKUP_FAILED",
        "BACKUP_RESTORE_STARTED",
        "BACKUP_RESTORED",
        "BACKUP_RESTORE_FAILED",
        # Infrastructure
        "INFRASTRUCTURE_CHECK_STARTED",
        "INFRASTRUCTURE_HEALTHY",
        "INFRASTRUCTURE_DEGRADED",
        "INFRASTRUCTURE_UNAVAILABLE",
        "INFRASTRUCTURE_RECONCILIATION_STARTED",
        "INFRASTRUCTURE_RECONCILED",
        "INFRASTRUCTURE_RECONCILIATION_FAILED",
        # Content
        "CONTENT_INSTALL_REQUESTED",
        "CONTENT_INSTALL_STARTED",
        "CONTENT_INSTALLED",
        "CONTENT_INSTALL_FAILED",
        "CONTENT_UPDATE_STARTED",
        "CONTENT_UPDATED",
        "CONTENT_UPDATE_FAILED",
        "CONTENT_REMOVED",
        "CONTENT_VERIFY_FAILED",
        # Authentication
        "AUTH_LOGIN_SUCCEEDED",
        "AUTH_LOGIN_FAILED",
        "AUTH_SESSION_CREATED",
        "AUTH_SESSION_REVOKED",
        "PERMISSION_DENIED",
        "STEAM_AUTH_REQUIRED",
        "STEAM_AUTH_SUCCEEDED",
        "STEAM_AUTH_FAILED",
        # Broadcast
        "BROADCAST_REQUESTED",
        "BROADCAST_DISPATCH_STARTED",
        "BROADCAST_DELIVERED",
        "BROADCAST_PARTIALLY_DELIVERED",
        "BROADCAST_FAILED",
        # Legacy/runtime compatibility candidates
        "SERVER_STARTED",
        "SERVER_STOPPED",
        "SERVER_CRASH",
        "PLAYER_CONNECTED",
        "PLAYER_DISCONNECTED",
        "PLAYER_DEATH",
        "MOD_UPDATED",
        "MOD_ERROR",
    }
)


def is_registered(event_type: str) -> bool:
    return event_type in EVENT_TYPES


def require_registered(event_type: str) -> str:
    if not is_registered(event_type):
        raise ValueError(f"unregistered event type: {event_type}")
    return event_type
