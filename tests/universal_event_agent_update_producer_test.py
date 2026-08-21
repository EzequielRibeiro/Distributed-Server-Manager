from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT_DIR / "database"
for path in (ROOT_DIR, DATABASE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_registration_repository import AgentRegistrationRepository
from agent_update_repository import AgentUpdateRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from core.events import EventPublisher, EventSeverity
from registry import installation_profile_identity
from registry_repository import RegistryRepository


def _repository(tmp_path: Path):
    backend = create_backend(
        DatabaseConfig(
            driver="sqlite",
            database=str(tmp_path / "agent-update-events.db"),
        )
    )
    backend.initialize()

    registry = RegistryRepository(backend)
    identity = installation_profile_identity(
        registry,
        profile="controller",
        hostname="event-producer-controller",
    )
    controller_id = identity["controller_id"]

    registration = AgentRegistrationRepository(backend)
    for suffix in ("a", "b"):
        registration.register(
            controller_id=controller_id,
            agent_id=f"agent-{suffix}",
            node_id=f"node-{suffix}",
            name=f"Agent {suffix.upper()}",
        )

    received = []
    publisher = EventPublisher(sink=received.append)
    repository = AgentUpdateRepository(
        backend,
        event_publisher=publisher,
    )
    return backend, repository, received


def test_available_version_emits_only_when_value_changes(tmp_path):
    backend, repository, received = _repository(tmp_path)
    try:
        repository.set_available_version("agent-a", "2.0.0")
        repository.set_available_version("agent-a", "2.0.0")

        assert [event.type for event in received] == ["AGENT_UPDATE_AVAILABLE"]
        event = received[0]
        assert event.source.type == "agent"
        assert event.source.id == "agent-a"
        assert event.scope.agent_id == "agent-a"
        assert event.severity is EventSeverity.NOTICE
        assert event.data["available_version"] == "2.0.0"
    finally:
        backend.close()


def test_rollout_update_events_share_correlation_id(tmp_path):
    backend, repository, received = _repository(tmp_path)
    try:
        rollout = repository.create_rollout(
            ["agent-a"],
            desired_version="2.1.0",
            channel="stable",
        )
        repository.mark_updating("agent-a")
        repository.reconcile_after_heartbeat("agent-a", "2.1.0", "online")

        assert [event.type for event in received] == [
            "AGENT_UPDATE_AVAILABLE",
            "AGENT_UPDATE_STARTED",
            "AGENT_UPDATE_COMPLETED",
        ]
        correlation_ids = {event.correlation_id for event in received}
        assert len(correlation_ids) == 1
        correlation_id = correlation_ids.pop()
        assert correlation_id is not None
        assert correlation_id.startswith("corr_")

        for event in received:
            assert event.data["rollout_id"] == rollout["rollout_id"]
            assert event.data["desired_version"] == "2.1.0"
            assert event.scope.agent_id == "agent-a"
    finally:
        backend.close()


def test_failed_update_emits_error_event_once(tmp_path):
    backend, repository, received = _repository(tmp_path)
    try:
        repository.create_rollout(["agent-a"], desired_version="2.2.0")
        repository.mark_updating("agent-a")
        repository.mark_failed("agent-a", "checksum mismatch")
        repository.mark_failed("agent-a", "checksum mismatch")

        failed = [event for event in received if event.type == "AGENT_UPDATE_FAILED"]
        assert len(failed) == 1
        assert failed[0].severity is EventSeverity.ERROR
        assert failed[0].data["last_error"] == "checksum mismatch"
    finally:
        backend.close()


def test_repository_remains_backward_compatible_without_publisher(tmp_path):
    backend = create_backend(
        DatabaseConfig(
            driver="sqlite",
            database=str(tmp_path / "agent-update-no-events.db"),
        )
    )
    try:
        backend.initialize()
        registry = RegistryRepository(backend)
        identity = installation_profile_identity(
            registry,
            profile="controller",
            hostname="no-event-controller",
        )
        AgentRegistrationRepository(backend).register(
            controller_id=identity["controller_id"],
            agent_id="agent-a",
            node_id="node-a",
            name="Agent A",
        )

        repository = AgentUpdateRepository(backend)
        rollout = repository.create_rollout(["agent-a"], desired_version="3.0.0")
        state = repository.mark_updating("agent-a")

        assert rollout["desired_version"] == "3.0.0"
        assert state["update_status"] == "updating"
    finally:
        backend.close()
