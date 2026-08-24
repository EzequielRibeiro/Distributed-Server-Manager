from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"
for path in (str(DASHBOARD), str(DATABASE)):
    if path not in sys.path:
        sys.path.insert(0, path)

instance_runtime_command = importlib.import_module("instance_runtime_command")


class _Row(dict):
    pass


class _Session:
    def __init__(self, row):
        self.row = row

    def execute(self, statement, parameters):
        assert "SELECT agent_id FROM instances" in statement
        return self

    def fetchone(self):
        return self.row


class _Context:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return _Session(self.row)

    def __exit__(self, exc_type, exc, tb):
        return False


class _Repository:
    dialect = type("Dialect", (), {"placeholder": "?"})()

    def __init__(self, backend):
        self.backend = backend
        self.snapshots = [
            {"status": "queued"},
            {
                "status": "completed",
                "result": {
                    "status": "completed",
                    "result": {"observed_state": "running"},
                },
            },
        ]
        self.enqueued = None

    def initialize(self):
        return None

    def session(self):
        return _Context(_Row(agent_id="agent-01"))

    def enqueue(self, **payload):
        self.enqueued = payload
        return {"command_id": "instance-cmd-test"}

    def snapshot(self, command_id):
        assert command_id == "instance-cmd-test"
        return self.snapshots.pop(0)


def test_execute_routes_lifecycle_only_through_assigned_agent(tmp_path, monkeypatch):
    instances = tmp_path / "instances" / "node-legacy-name" / "minecraft" / "srv-01"
    instances.mkdir(parents=True)

    repository_holder = {}

    def repository_factory(backend):
        repository = _Repository(backend)
        repository_holder["value"] = repository
        return repository

    monkeypatch.setattr(instance_runtime_command, "DSM_ROOT", tmp_path)
    monkeypatch.setattr(instance_runtime_command, "backend_from_environment", lambda: object())
    monkeypatch.setattr(instance_runtime_command, "AgentInstanceRuntimeRepository", repository_factory)
    monkeypatch.setenv("DSM_USER", "customer-user")

    result = instance_runtime_command.execute(
        "start",
        str(instances),
        timeout_seconds=2,
        poll_seconds=0.001,
    )

    assert result["ok"] is True
    assert result["agent_id"] == "agent-01"
    assert result["instance_id"] == "srv-01"
    assert result["observed_state"] == "running"
    assert repository_holder["value"].enqueued == {
        "agent_id": "agent-01",
        "instance_id": "srv-01",
        "action": "start",
        "requested_by": "customer-user",
    }


def test_execute_rejects_unregistered_instance_without_fallback(tmp_path, monkeypatch):
    instance = tmp_path / "instances" / "node" / "game" / "missing"
    instance.mkdir(parents=True)

    class MissingRepository(_Repository):
        def session(self):
            return _Context(None)

    monkeypatch.setattr(instance_runtime_command, "DSM_ROOT", tmp_path)
    monkeypatch.setattr(instance_runtime_command, "backend_from_environment", lambda: object())
    monkeypatch.setattr(instance_runtime_command, "AgentInstanceRuntimeRepository", MissingRepository)

    try:
        instance_runtime_command.execute("start", str(instance))
    except ValueError as exc:
        assert str(exc) == "Instance not found"
    else:
        raise AssertionError("unregistered instance must be rejected")


def test_instance_shell_contains_no_local_process_fallback():
    script = (ROOT / "dashboard" / "api" / "instance.sh").read_text(encoding="utf-8")
    forbidden = ("process_start", "process_stop", "process_restart", "pid.sh", "tree.sh", "process.sh")
    assert all(token not in script for token in forbidden)
    assert "instance_runtime_command.py" in script


def test_runtime_command_script_imports_from_clean_python_process():
    script = ROOT / "dashboard" / "instance_runtime_command.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd="/tmp",
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "usage: instance_runtime_command.py" in completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr
