import pytest

from core.events import EventContext, EventPublisher, EventSource


def test_root_context_generates_correlation_id():
    context = EventContext.root()

    assert context.correlation_id.startswith("corr_")
    assert context.causation_id is None


def test_publisher_applies_context_to_event():
    context = EventContext.root("corr-workflow-1")
    publisher = EventPublisher()

    event = publisher.publish(
        "INSTANCE_CREATE_REQUESTED",
        source=EventSource(type="controller", id="controller-1"),
        context=context,
    )

    assert event.correlation_id == "corr-workflow-1"
    assert event.causation_id is None


def test_context_from_event_preserves_workflow_and_tracks_parent():
    publisher = EventPublisher()
    root_context = EventContext.root("corr-workflow-2")

    requested = publisher.publish(
        "INSTANCE_CREATE_REQUESTED",
        source=EventSource(type="controller", id="controller-1"),
        context=root_context,
    )
    placement_context = EventContext.from_event(requested)
    selected = publisher.publish(
        "PLACEMENT_SELECTED",
        source=EventSource(type="placement", id="placement-1"),
        context=placement_context,
    )

    assert selected.correlation_id == requested.correlation_id
    assert selected.causation_id == requested.id


def test_context_can_continue_legacy_event_without_correlation_id():
    publisher = EventPublisher()
    legacy_event = publisher.publish(
        "SERVER_STARTED",
        source=EventSource(type="runtime", id="legacy-runtime"),
    )

    context = EventContext.from_event(legacy_event)

    assert context.correlation_id == (
        "corr_" + legacy_event.id.removeprefix("evt_")
    )
    assert context.causation_id == legacy_event.id


def test_caused_by_updates_parent_without_changing_correlation():
    publisher = EventPublisher()
    context = EventContext.root("corr-workflow-3")
    first = publisher.publish(
        "BACKUP_REQUESTED",
        source=EventSource(type="backup", id="backup-job-1"),
        context=context,
    )

    child_context = context.caused_by(first)

    assert child_context.correlation_id == context.correlation_id
    assert child_context.causation_id == first.id


def test_context_cannot_be_mixed_with_explicit_correlation_fields():
    publisher = EventPublisher()

    with pytest.raises(ValueError, match="context cannot be combined"):
        publisher.publish(
            "BACKUP_STARTED",
            source=EventSource(type="backup", id="backup-job-1"),
            context=EventContext.root(),
            correlation_id="corr-explicit",
        )
