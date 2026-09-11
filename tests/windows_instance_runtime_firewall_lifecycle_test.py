from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "agents" / "windows" / "runtime" / "instance_runtime.py"


def _load_runtime(monkeypatch):
    adapters = types.ModuleType("adapters")

    class AdapterError(RuntimeError):
        pass

    adapters.AdapterError = AdapterError
    adapters.resolve_adapter = lambda _record: None
    monkeypatch.setitem(sys.modules, "adapters", adapters)

    firewall = types.ModuleType("managed_firewall")
    firewall.reconcile = lambda _record: {"managed": True, "changed": False}
    firewall.remove = lambda _record: {"managed": True, "changed": False}
    monkeypatch.setitem(sys.modules, "managed_firewall", firewall)

    metrics = types.ModuleType("runtime_metrics")
    metrics.increment = lambda _name: None
    monkeypatch.setitem(sys.modules, "runtime_metrics", metrics)

    operations = types.ModuleType("runtime_operations")

    @contextmanager
    def runtime_operation(*_args, **_kwargs):
        yield

    operations.runtime_operation = runtime_operation
    monkeypatch.setitem(sys.modules, "runtime_operations", operations)

    spec = importlib.util.spec_from_file_location(
        "windows_instance_runtime_firewall_lifecycle",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, firewall


def _record(*, managed=True, observed_state="stopped"):
    record = {
        "instance_id": "win-instance-001",
        "agent_id": "agent-win-001",
        "adapter": "fake",
        "observed_state": observed_state,
        "network": {"bind": "0.0.0.0"},
        "ports": {
            "game": {"port": 2302, "protocol": "udp"},
        },
    }
    if managed:
        record["catalog_runtime_policy"] = {
            "runtime_id": "dayz",
            "network_exposure": [
                {
                    "name": "game",
                    "protocol": "udp",
                    "exposure": "public",
                }
            ],
        }
    return record


def _adapter(events, action):
    state = {
        "available": True,
        "active_state": "inactive" if action == "stop" else "active",
    }

    def invoke(_record):
        events.append(f"adapter:{action}")
        return {"state": state}

    return types.SimpleNamespace(name="fake", **{action: invoke})


def _wire(module, record, adapter, events):
    module._owned = lambda _config, _instance_id: record
    module.resolve_adapter = lambda _record: adapter

    def persist(updated):
        events.append(f"persist:{updated['desired_state']}")
        return dict(updated)

    module.register_instance = persist


def test_register_instance_preserves_firewall_policy_and_network(monkeypatch, tmp_path):
    module, _firewall = _load_runtime(monkeypatch)
    module.INSTANCE_DIR = tmp_path / "instances"
    record = _record()

    registered = module.register_instance(record)
    persisted = module.get_instance(record["instance_id"])

    assert registered["catalog_runtime_policy"] == record["catalog_runtime_policy"]
    assert registered["network"] == record["network"]
    assert persisted["catalog_runtime_policy"] == record["catalog_runtime_policy"]
    assert persisted["network"] == record["network"]


@pytest.mark.parametrize("action", ["start", "restart"])
def test_managed_start_and_restart_reconcile_before_process(monkeypatch, action):
    module, firewall = _load_runtime(monkeypatch)
    events = []
    record = _record(observed_state="stopped")
    adapter = _adapter(events, action)
    _wire(module, record, adapter, events)

    def reconcile(_record):
        events.append("firewall:reconcile")
        return {"managed": True, "changed": True, "rules": ["game"]}

    firewall.reconcile = reconcile

    result = module.lifecycle(
        {"agent_id": record["agent_id"]},
        record["instance_id"],
        action,
    )

    assert events[:2] == ["firewall:reconcile", f"adapter:{action}"]
    assert events[-1] == "persist:running"
    assert result["firewall"]["managed"] is True
    assert result["observed_state"] == "running"


def test_stop_persists_stopped_before_firewall_removal(monkeypatch):
    module, firewall = _load_runtime(monkeypatch)
    events = []
    record = _record(observed_state="running")
    adapter = _adapter(events, "stop")
    _wire(module, record, adapter, events)

    def remove(_record):
        events.append("firewall:remove")
        return {"managed": True, "changed": True}

    firewall.remove = remove

    result = module.lifecycle(
        {"agent_id": record["agent_id"]},
        record["instance_id"],
        "stop",
    )

    assert events == ["adapter:stop", "persist:stopped", "firewall:remove"]
    assert result["observed_state"] == "stopped"
    assert result["firewall"]["managed"] is True


def test_idempotent_stop_still_removes_managed_firewall(monkeypatch):
    module, firewall = _load_runtime(monkeypatch)
    events = []
    record = _record(observed_state="stopped")
    adapter = _adapter(events, "stop")
    _wire(module, record, adapter, events)

    def remove(_record):
        events.append("firewall:remove")
        return {"managed": True, "changed": False}

    firewall.remove = remove

    module.lifecycle(
        {"agent_id": record["agent_id"]},
        record["instance_id"],
        "stop",
    )

    assert events == ["adapter:stop", "persist:stopped", "firewall:remove"]


def test_firewall_removal_failure_keeps_persisted_state_stopped(monkeypatch):
    module, firewall = _load_runtime(monkeypatch)
    events = []
    persisted = []
    record = _record(observed_state="running")
    adapter = _adapter(events, "stop")
    module._owned = lambda _config, _instance_id: record
    module.resolve_adapter = lambda _record: adapter

    def persist(updated):
        persisted.append(dict(updated))
        events.append(f"persist:{updated['desired_state']}")
        return dict(updated)

    module.register_instance = persist

    def remove(_record):
        events.append("firewall:remove")
        raise RuntimeError("firewall teardown failed")

    firewall.remove = remove

    with pytest.raises(RuntimeError, match="firewall teardown failed"):
        module.lifecycle(
            {"agent_id": record["agent_id"]},
            record["instance_id"],
            "stop",
        )

    assert events == ["adapter:stop", "persist:stopped", "firewall:remove"]
    assert persisted[-1]["desired_state"] == "stopped"
    assert persisted[-1]["observed_state"] == "stopped"


@pytest.mark.parametrize("action", ["start", "restart"])
def test_reconcile_failure_blocks_process_start_or_restart(monkeypatch, action):
    module, firewall = _load_runtime(monkeypatch)
    events = []
    record = _record(observed_state="stopped")
    adapter = _adapter(events, action)
    _wire(module, record, adapter, events)

    def reconcile(_record):
        events.append("firewall:reconcile")
        raise RuntimeError("firewall reconcile failed")

    firewall.reconcile = reconcile

    with pytest.raises(RuntimeError, match="firewall reconcile failed"):
        module.lifecycle(
            {"agent_id": record["agent_id"]},
            record["instance_id"],
            action,
        )

    assert events == ["firewall:reconcile"]


@pytest.mark.parametrize("action", ["start", "restart", "stop"])
def test_legacy_runtime_without_catalog_policy_skips_firewall(monkeypatch, action):
    module, firewall = _load_runtime(monkeypatch)
    events = []
    record = _record(managed=False, observed_state="stopped")
    adapter = _adapter(events, action)
    _wire(module, record, adapter, events)

    def unexpected(_record):
        raise AssertionError("legacy runtime must not touch managed firewall")

    firewall.reconcile = unexpected
    firewall.remove = unexpected

    result = module.lifecycle(
        {"agent_id": record["agent_id"]},
        record["instance_id"],
        action,
    )

    assert "firewall" not in result
    assert events[0] == f"adapter:{action}"
