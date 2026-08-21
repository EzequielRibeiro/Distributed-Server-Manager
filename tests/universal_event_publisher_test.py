import pytest

from core.events import (
    EventPublisher,
    EventScope,
    EventSeverity,
    EventSource,
    EventValidationError,
    publish,
)


def test_publish_builds_registered_event():
    event = publish(
        "AGENT_OFFLINE",
        source=EventSource(type="agent", id="agent-a"),
        severity=EventSeverity.WARNING,
        scope=EventScope(controller_id="controller-1", agent_id="agent-a"),
        data={"reason": "heartbeat_timeout"},
        correlation_id="corr-123",
    )

    assert event.type == "AGENT_OFFLINE"
    assert event.severity is EventSeverity.WARNING
    assert event.scope.agent_id == "agent-a"
    assert event.data["reason"] == "heartbeat_timeout"
    assert event.correlation_id == "corr-123"


def test_publisher_delivers_valid_event_to_sink():
    received = []
    publisher = EventPublisher(sink=received.append)

    event = publisher.publish(
        "BACKUP_CREATED",
        source=EventSource(type="backup", id="backup-1"),
        data={"path": "/backup/demo.tar"},
    )

    assert received == [event]


def test_unregistered_event_is_rejected_before_sink():
    received = []
    publisher = EventPublisher(sink=received.append)

    with pytest.raises(EventValidationError, match="unregistered event type"):
        publisher.publish(
            "SOMETHING_RANDOM_HAPPENED",
            source=EventSource(type="test", id="test-1"),
        )

    assert received == []


def test_non_json_payload_is_rejected():
    publisher = EventPublisher()

    with pytest.raises(EventValidationError, match="JSON serializable"):
        publisher.publish(
            "INSTANCE_CREATED",
            source=EventSource(type="instance", id="instance-1"),
            data={"bad": object()},
        )
