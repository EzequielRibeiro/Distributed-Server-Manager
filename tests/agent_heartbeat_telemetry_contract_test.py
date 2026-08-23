#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
DATABASE = ROOT / "database"
sys.path.insert(0, str(DASHBOARD))
sys.path.insert(0, str(DATABASE))

from agent_heartbeat_api import _observability_from_heartbeat, _telemetry_from_heartbeat


class AgentHeartbeatTelemetryContractTest(unittest.TestCase):
    def test_runtime_metrics_telemetry_is_discovered(self):
        telemetry = {
            "schema_version": 1,
            "host": {
                "cpu_usage_pct": 12.5,
                "memory": {"usage_pct": 33.0},
                "disk": {"usage_pct": 44.0},
                "network": {"rx_bytes_per_second": 1000.0, "tx_bytes_per_second": 500.0},
                "temperature_c": 51.0,
            },
            "agent": {"cpu_usage_pct": 1.5, "memory_rss_bytes": 123456, "threads": 4},
            "top_processes": [],
        }
        body = {"instance_runtime_metrics": {"telemetry": telemetry}}
        self.assertEqual(_telemetry_from_heartbeat(body), telemetry)

        samples = _observability_from_heartbeat("agent-01", body)
        names = {item["metric_name"] for item in samples}
        for expected in (
            "capivara.host.cpu.usage_pct",
            "capivara.host.memory.usage_pct",
            "capivara.host.disk.usage_pct",
            "capivara.host.network.rx_bytes_per_second",
            "capivara.host.network.tx_bytes_per_second",
            "capivara.host.temperature_c",
            "capivara.agent.cpu.usage_pct",
            "capivara.agent.memory.rss_bytes",
            "capivara.agent.threads",
        ):
            self.assertIn(expected, names)



class AgentHeartbeatPostgresqlMetadataCompatibilityTest(unittest.TestCase):
    def test_metadata_json_already_decoded_as_dict_is_supported(self):
        from dashboard.agent_heartbeat_api import _store_agent_metadata

        class Row(dict):
            pass

        class Result:
            def fetchone(self):
                return Row({
                    "metadata_json": {
                        "existing": "preserved",
                        "telemetry": {
                            "host": {
                                "cpu_usage_pct": 1.0
                            }
                        }
                    }
                })

        class Session:
            def __init__(self):
                self.updated = None

            def execute(self, sql, params=()):
                if sql.lstrip().upper().startswith("SELECT"):
                    return Result()

                if sql.lstrip().upper().startswith("UPDATE"):
                    self.updated = params
                    return None

            def close(self):
                pass

        class Transaction:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        class Dialect:
            placeholder = "%s"

        class Backend:
            def __init__(self):
                self.session = Session()

            def transaction(self):
                return Transaction()

        backend = Backend()

        import dashboard.agent_heartbeat_api as module

        original_session = module.AlertSession
        original_dialect = module.dialect_for_backend

        try:
            module.AlertSession = lambda backend, connection: backend.session
            module.dialect_for_backend = lambda backend: Dialect()

            _store_agent_metadata(
                "agent-test",
                {
                    "telemetry": {
                        "host": {
                            "cpu_usage_pct": 42.5
                        }
                    }
                },
                backend=backend,
            )
        finally:
            module.AlertSession = original_session
            module.dialect_for_backend = original_dialect

        self.assertIsNotNone(backend.session.updated)

        import json
        metadata = json.loads(backend.session.updated[0])

        self.assertEqual(metadata["existing"], "preserved")
        self.assertEqual(
            metadata["telemetry"]["host"]["cpu_usage_pct"],
            42.5,
        )


if __name__ == "__main__":
    unittest.main()
