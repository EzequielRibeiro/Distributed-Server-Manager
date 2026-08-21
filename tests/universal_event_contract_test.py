from datetime import datetime

import pytest

from core.events import (
    EventScope,
    EventSeverity,
    EventSource,
    UniversalEvent,
    is_registered,
    require_registered,
)


def test_universal_event_serializes_expected_envelope():
    event = UniversalEvent(
        type="AGENT_OFFLINE",
        source=EventSource(type="agent", id="agent-node-a"),
        severity=EventSeverity.WARNING,
        scope=EventScope(
            controller_id="controller-01",
            agent_id="agent-node-a",
        ),
        correlation_id="corr-123",
        causation_id="evt-parent",
        data={"reason": "heartbeat_timeout"},
    )

    payload = event.to_dict()

    assert payload["id"].startswith("evt_")
    assert payload["type"] == "AGENT_OFFLINE"
    assert payload["version"] == 1
    assert payload["severity"] == "warning"
    assert payload["source"] == {"type": "agent", "id": "agent-node-a"}
    assert payload["scope"] == {
        "controller_id": "controller-01",
        "agent_id": "agent-node-a",
    }
    assert payload["correlation_id"] == "corr-123"
    assert payload["causation_id"] == "evt-parent"
    assert payload["data"] == {"reason": "heartbeat_timeout"}
    assert payload["timestamp"].endswith("Z")
    datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))


def test_event_requires_uppercase_type():
    with pytest.raises(ValueError, match="uppercase"):
        UniversalEvent(
            type="agent_offline",
            source=EventSource(type="agent", id="agent-node-a"),
        )


def test_event_source_requires_identity():
    with pytest.raises(ValueError, match="source id"):
        EventSource(type="agent", id="")


def test_registry_contains_initial_phase_21_events():
    assert is_registered("AGENT_ENROLLED")
    assert is_registered("PLACEMENT_SELECTED")
    assert is_registered("INSTANCE_INSTALL_COMPLETED")
    assert is_registered("PORT_CONFLICT")
    assert is_registered("BACKUP_CREATED")
    assert is_registered("INFRASTRUCTURE_DEGRADED")
    assert is_registered("BROADCAST_DELIVERED")


def test_registry_rejects_unknown_event_type():
    with pytest.raises(ValueError, match="unregistered event type"):
        require_registered("UNKNOWN_EVENT")
