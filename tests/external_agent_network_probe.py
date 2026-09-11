#!/usr/bin/env python3
"""Execute real Linux Agent network actions for the P4 external-network gate."""
from __future__ import annotations

import copy
import json
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import agent as linux_agent


def emit(value) -> None:
    print(json.dumps(value, sort_keys=True, default=str), flush=True)


class _FixtureProfile:
    profile_version = 1

    def build_runtime_spec(self, instance, context):
        working = Path(str(context["instance_state_root"]))
        working.mkdir(parents=True, exist_ok=True)
        install = Path(str(context["install_path"]))
        return {
            "instance_id": instance["instance_id"],
            "agent_id": instance["agent_id"],
            "runtime_id": instance["runtime_id"],
            "game_id": instance["game_id"],
            "environment_id": instance["environment_id"],
            "adapter": "systemd",
            "profile": "external-e2e",
            "profile_version": 1,
            "working_directory": str(working),
            "executable": str(install / "server-bin"),
            "arguments": [],
            "environment": {},
            "user": "capivara-instance",
            "desired_state": "stopped",
            "ports": copy.deepcopy(context["ports"]),
        }


class _RuntimeContractHarness:
    def __init__(self, config, instance_a: str, instance_b: str):
        import game_runtime
        import instance_runtime
        import privileged_firewall
        import privileged_materialization
        import provisioning_executor
        import provisioning_state

        self.config = config
        self.instance_a = instance_a
        self.instance_b = instance_b
        self.game_runtime = game_runtime
        self.instance_runtime = instance_runtime
        self.firewall = privileged_firewall
        self.materialization = privileged_materialization
        self.executor = provisioning_executor
        self.provisioning_state = provisioning_state
        self.real_public_rules = privileged_firewall.public_rules
        self.runtime_state: dict[str, str] = {}
        self.firewall_state: dict[str, list[dict]] = {}
        self.specs: dict[str, dict] = {}
        self.events: list[dict] = []
        self.lifecycle_results: list[dict] = []
        self.private_closed = True
        self.reconcile_before_start_restart = True
        self.remove_after_stopped = True
        self.isolation_between_instances = True
        self._install()

    def _install(self):
        harness = self

        class Adapter:
            name = "systemd"

            def status(self, record):
                active = harness.runtime_state.get(record["instance_id"], "stopped") == "running"
                return {"available": True, "active_state": "active" if active else "inactive"}

            def doctor(self, record):
                return {"status": "healthy", "findings": []}

            def start(self, record):
                harness._require_firewall_before_runtime(record, "start")
                instance_id = record["instance_id"]
                changed = harness.runtime_state.get(instance_id, "stopped") != "running"
                harness.runtime_state[instance_id] = "running"
                harness.events.append({"stage": "adapter_start", "instance_id": instance_id, "changed": changed})
                return {"changed": changed, "idempotent": not changed, "state": self.status(record)}

            def restart(self, record):
                harness._require_firewall_before_runtime(record, "restart")
                instance_id = record["instance_id"]
                harness.runtime_state[instance_id] = "running"
                harness.events.append({"stage": "adapter_restart", "instance_id": instance_id, "changed": True})
                return {"changed": True, "state": self.status(record)}

            def stop(self, record):
                instance_id = record["instance_id"]
                changed = harness.runtime_state.get(instance_id, "stopped") != "stopped"
                harness.runtime_state[instance_id] = "stopped"
                harness.events.append({"stage": "adapter_stop", "instance_id": instance_id, "changed": changed})
                return {"changed": changed, "idempotent": not changed, "state": self.status(record)}

        adapter = Adapter()
        self.instance_runtime.resolve_adapter = lambda record: adapter
        self.game_runtime.resolve_profile = lambda instance: _FixtureProfile()

        def execute_game_data(command):
            selection = command.get("selection") if isinstance(command, dict) else {}
            token = str((selection or {}).get("fixture_instance") or "shared")
            install = Path(os.environ["CAPIVARA_AGENT_STATE_DIR"]) / "fixture-content" / token
            install.mkdir(parents=True, exist_ok=True)
            binary = install / "server-bin"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
            return {
                "provider": "fixture",
                "game": "external-e2e",
                "version": "1",
                "target_path": str(install),
            }

        def materialize(config, spec):
            instance_id = str(spec["instance_id"])
            self.instance_runtime.register_instance(spec)
            self.specs[instance_id] = copy.deepcopy(spec)
            self.runtime_state.setdefault(instance_id, "stopped")
            self.events.append({"stage": "materialize", "instance_id": instance_id})
            return {"operation": {"changed": True}}

        def firewall_reconcile(spec, *, rules=None):
            instance_id = str(spec["instance_id"])
            desired = self.real_public_rules(spec) if rules is None else [dict(item) for item in rules]
            exposure = {
                str(item.get("name")): str(item.get("exposure"))
                for item in ((spec.get("catalog_runtime_policy") or {}).get("network_exposure") or [])
                if isinstance(item, dict)
            }
            if exposure.get("game") != "public" or exposure.get("admin") != "private":
                self.private_closed = False
                raise AssertionError(f"unexpected catalog exposure for {instance_id}: {exposure}")
            if any(str(rule.get("name")) == "admin" for rule in desired):
                self.private_closed = False
                raise AssertionError("private admin port reached public firewall rules")
            previous = self.firewall_state.get(instance_id, [])
            changed = previous != desired
            self.firewall_state[instance_id] = copy.deepcopy(desired)
            self.events.append(
                {
                    "stage": "firewall_reconcile",
                    "instance_id": instance_id,
                    "changed": changed,
                    "rules": copy.deepcopy(desired),
                }
            )
            return {"backend": "external-e2e-contract", "changed": changed, "rules": desired}

        def firewall_remove(spec):
            instance_id = str(spec["instance_id"])
            current = self.instance_runtime.get_instance(instance_id)
            if current is not None and (
                str(current.get("desired_state") or "").lower() != "stopped"
                or str(current.get("observed_state") or "").lower() != "stopped"
            ):
                self.remove_after_stopped = False
                raise AssertionError(f"firewall teardown before stopped state: {instance_id}")
            self.events.append({"stage": "firewall_remove", "instance_id": instance_id})
            return firewall_reconcile(spec, rules=[])

        def remove_materialized(config, instance_id):
            instance_id = str(instance_id)
            if self.runtime_state.get(instance_id, "stopped") != "stopped":
                self.remove_after_stopped = False
                raise AssertionError(f"runtime removal before adapter stopped: {instance_id}")
            if self.firewall_state.get(instance_id):
                self.remove_after_stopped = False
                raise AssertionError(f"runtime removal before firewall teardown: {instance_id}")
            if instance_id == self.instance_a:
                if self.runtime_state.get(self.instance_b) != "running" or not self.firewall_state.get(self.instance_b):
                    self.isolation_between_instances = False
                    raise AssertionError("teardown of instance A affected running instance B")
            try:
                (Path(self.instance_runtime.INSTANCE_DIR) / f"{instance_id}.json").unlink()
            except FileNotFoundError:
                pass
            self.events.append({"stage": "materialization_remove", "instance_id": instance_id})
            return {
                "firewall": {"backend": "external-e2e-contract", "changed": False, "rules": []},
                "operation": {"changed": True},
            }

        def initial_reconcile(config, instance_id):
            record = self.instance_runtime.get_instance(instance_id)
            if not isinstance(record, dict):
                raise AssertionError(f"RuntimeSpec was not materialized: {instance_id}")
            self.events.append({"stage": "initial_reconcile", "instance_id": instance_id})
            return {"observed_state": "stopped"}

        self.executor.execute_game_data = execute_game_data
        self.materialization.materialize = materialize
        self.materialization.remove = remove_materialized
        self.firewall.reconcile = firewall_reconcile
        self.firewall.remove = firewall_remove
        self.executor.runtime_materialization.reconcile = initial_reconcile

        def synchronous_stage(command, *, config_path):
            if not isinstance(command, dict):
                return False
            provisioning_id = str(command.get("provisioning_id") or "")
            request_path, result_path, _ = self.provisioning_state.paths(provisioning_id)
            existing = self.provisioning_state.read_json(result_path)
            if existing and str(existing.get("status") or "").lower() in {"running", "completed", "failed"}:
                return False
            self.provisioning_state.write_json(request_path, command)
            self.provisioning_state.write_json(
                result_path,
                {
                    "provisioning_id": provisioning_id,
                    "instance_id": command["instance_id"],
                    "status": "running",
                    "current_step": "staged",
                    "progress": 1,
                },
            )
            self.executor.execute(self.config, command, result_path)
            return True

        linux_agent.stage_provisioning_command = synchronous_stage

    def _require_firewall_before_runtime(self, record, action: str):
        instance_id = str(record["instance_id"])
        rules = self.firewall_state.get(instance_id)
        if not rules:
            self.reconcile_before_start_restart = False
            raise AssertionError(f"{action} reached adapter before firewall reconcile: {instance_id}")
        latest_firewall = max(
            (index for index, event in enumerate(self.events)
             if event["stage"] == "firewall_reconcile" and event["instance_id"] == instance_id),
            default=-1,
        )
        latest_runtime = max(
            (index for index, event in enumerate(self.events)
             if event["stage"] in {"adapter_start", "adapter_restart"} and event["instance_id"] == instance_id),
            default=-1,
        )
        if latest_firewall <= latest_runtime:
            self.reconcile_before_start_restart = False
            raise AssertionError(f"{action} did not receive a fresh firewall reconcile: {instance_id}")

    def drive(self, max_heartbeats: int = 80) -> dict:
        final_seen = False
        for _ in range(max_heartbeats):
            response = linux_agent.heartbeat(self.config)
            state = response.get("instance_state") if isinstance(response.get("instance_state"), dict) else {}
            if str(state.get("status") or "").lower() in {"completed", "failed"} and state.get("action"):
                item = {
                    "command_id": state.get("command_id"),
                    "instance_id": state.get("instance_id"),
                    "action": state.get("action"),
                    "status": state.get("status"),
                    "result": state.get("result"),
                }
                if not self.lifecycle_results or self.lifecycle_results[-1].get("command_id") != item["command_id"]:
                    self.lifecycle_results.append(item)
            if (
                str(state.get("status") or "").lower() == "completed"
                and str(state.get("action") or "").lower() == "remove"
                and str(state.get("instance_id") or "") == self.instance_b
                and not isinstance(response.get("instance_command"), dict)
            ):
                final_seen = True
                linux_agent.heartbeat(self.config)
                break
        if not final_seen:
            raise AssertionError("instance lifecycle did not reach final teardown")

        if set(self.specs) != {self.instance_a, self.instance_b}:
            raise AssertionError(f"missing RuntimeSpec snapshots: {sorted(self.specs)}")
        port_sets = {
            instance_id: {
                (str(value.get("protocol")), int(value.get("port")))
                for value in spec.get("ports", {}).values()
                if isinstance(value, dict)
            }
            for instance_id, spec in self.specs.items()
        }
        if port_sets[self.instance_a] & port_sets[self.instance_b]:
            self.isolation_between_instances = False
            raise AssertionError("instance port sets overlap")

        start_events = [
            event for event in self.events
            if event["stage"] == "adapter_start" and event["instance_id"] == self.instance_a
        ]
        stop_events = [
            event for event in self.events
            if event["stage"] == "adapter_stop" and event["instance_id"] == self.instance_a
        ]
        idempotent_start = len(start_events) >= 2 and start_events[0]["changed"] and not start_events[1]["changed"]
        idempotent_stop = len(stop_events) >= 2 and stop_events[0]["changed"] and not stop_events[1]["changed"]
        if not idempotent_start or not idempotent_stop:
            raise AssertionError("repeated start/stop did not remain idempotent")
        if any(self.firewall_state.get(instance_id) for instance_id in (self.instance_a, self.instance_b)):
            raise AssertionError("firewall desired state remained after teardown")
        if any(
            (Path(self.instance_runtime.INSTANCE_DIR) / f"{instance_id}.json").exists()
            for instance_id in (self.instance_a, self.instance_b)
        ):
            raise AssertionError("instance RuntimeSpec remained after teardown")

        return {
            "completed": True,
            "runtime_specs": {
                instance_id: {
                    "ports": copy.deepcopy(spec.get("ports")),
                    "catalog_runtime_policy": copy.deepcopy(spec.get("catalog_runtime_policy")),
                }
                for instance_id, spec in self.specs.items()
            },
            "private_closed": self.private_closed,
            "reconcile_before_start_restart": self.reconcile_before_start_restart,
            "remove_after_stopped": self.remove_after_stopped,
            "idempotent_start": idempotent_start,
            "idempotent_stop": idempotent_stop,
            "isolation_between_instances": self.isolation_between_instances,
            "firewall_empty_after_teardown": not any(self.firewall_state.values()),
            "lifecycle_results": self.lifecycle_results,
            "events": self.events,
        }


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "resolve":
        hostname = sys.argv[2]
        started = time.perf_counter()
        address = socket.gethostbyname(hostname)
        emit({"hostname": hostname, "address": address, "dns_ms": round((time.perf_counter() - started) * 1000, 3)})
        return 0

    config = linux_agent._load_config()
    if action == "enroll":
        started = time.perf_counter()
        enrolled = linux_agent.enroll(config)
        emit({
            "agent_id": enrolled.get("agent_id"),
            "controller_id": enrolled.get("controller_id"),
            "credential_id": enrolled.get("credential_id"),
            "pairing_token_present": bool(enrolled.get("pairing_token")),
            "rtt_ms": round((time.perf_counter() - started) * 1000, 3),
        })
        return 0

    if action == "heartbeat":
        started = time.perf_counter()
        result = linux_agent.heartbeat(config)
        emit({
            "agent_id": result.get("agent_id"),
            "health_status": result.get("health_status"),
            "status": result.get("status"),
            "doctor_state": result.get("doctor_state"),
            "doctor_command": bool(result.get("doctor_command")),
            "rtt_ms": round((time.perf_counter() - started) * 1000, 3),
        })
        return 0

    if action == "instance-cycle":
        if len(sys.argv) != 4:
            raise SystemExit("usage: external_agent_network_probe.py instance-cycle INSTANCE_A INSTANCE_B")
        harness = _RuntimeContractHarness(config, sys.argv[2], sys.argv[3])
        emit(harness.drive())
        return 0

    raise SystemExit(f"unsupported action: {action}")


if __name__ == "__main__":
    raise SystemExit(main())
