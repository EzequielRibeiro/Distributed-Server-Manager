import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT_DIR / "database"
if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))

from backend import DatabaseConfig
from backends.sqlite_backend import SQLiteBackend
from event_repository import EventRepository
from core.events import EventPublisher, EventScope, EventSeverity, EventSource


EVENT_MIGRATION_MARKERS = {
    "event_version",
    "occurred_at",
    "source_type",
    "source_id",
    "controller_id",
    "agent_id",
    "customer_id",
    "correlation_id",
    "causation_id",
}


def _repository(tmp_path: Path) -> EventRepository:
    backend = SQLiteBackend(
        DatabaseConfig(
            driver="sqlite",
            database=str(tmp_path / "events.db"),
        )
    )
    return EventRepository(backend)


def test_repository_persists_and_rehydrates_universal_event(tmp_path):
    repository = _repository(tmp_path)
    repository.backend.initialize()

    # The original events table intentionally retains its instance_id FK.
    # Seed a real instance so the universal event test exercises that
    # compatibility constraint instead of bypassing it.
    with repository.backend.transaction() as connection:
        connection.execute(
            "INSERT INTO instances(id, game_id, name) VALUES (?, ?, ?)",
            ("instance-1", "test.game", "Test Instance"),
        )

    publisher = EventPublisher(sink=repository.store)

    event = publisher.publish(
        "AGENT_OFFLINE",
        source=EventSource(type="agent", id="agent-a"),
        severity=EventSeverity.WARNING,
        scope=EventScope(
            controller_id="controller-1",
            agent_id="agent-a",
            customer_id="customer-1",
            instance_id="instance-1",
        ),
        data={"reason": "heartbeat_timeout", "attempt": 2},
        correlation_id="corr-123",
        causation_id="evt_parent",
    )

    stored = repository.get(event.id)

    assert stored is not None
    assert stored.to_dict() == event.to_dict()


def test_repository_returns_none_for_unknown_event(tmp_path):
    repository = _repository(tmp_path)

    assert repository.get("evt_missing") is None


def test_event_migration_reaches_universal_store_schema(tmp_path):
    repository = _repository(tmp_path)
    status = repository.backend.initialize()

    assert int(status["current_migration"]) >= 27

    with repository.backend.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(events)").fetchall()
        }

    assert EVENT_MIGRATION_MARKERS <= columns


def test_event_store_migration_has_backend_parity():
    migration_name = "027_universal_event_store.sql"
    directories = (
        DATABASE_DIR / "migrations",
        DATABASE_DIR / "migrations_postgresql",
        DATABASE_DIR / "migrations_mysql",
    )

    for directory in directories:
        migration = directory / migration_name
        assert migration.is_file(), f"missing {migration}"
        content = migration.read_text(encoding="utf-8").lower()
        for marker in EVENT_MIGRATION_MARKERS:
            assert marker in content, f"{migration} missing {marker}"
