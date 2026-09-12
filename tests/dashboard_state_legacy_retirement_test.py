#!/usr/bin/env python3
"""Architecture regression for retired dashboard JSON state workers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RETIRED_WORKERS = (
    "dashboard_worker.sh",
    "metrics_worker.sh",
    "monitor_worker.sh",
)
RETIRED_PROJECTIONS = (
    "dashboard",
    "server",
    "metrics",
    "monitor",
)


def main() -> None:
    workers = ROOT / "dashboard" / "workers"
    for name in RETIRED_WORKERS:
        assert not (workers / name).exists(), f"retired worker returned: {name}"

    aggregate = (workers / "worker.sh").read_text(encoding="utf-8")
    executable_lines = [
        line for line in aggregate.splitlines() if not line.lstrip().startswith("#")
    ]
    for name in RETIRED_WORKERS:
        assert not any(name in line for line in executable_lines), (
            f"aggregate worker launches retired worker: {name}"
        )

    initializer = (ROOT / "dashboard" / "state" / "init_state.sh").read_text(
        encoding="utf-8"
    )
    file_block = initializer.split("FILES=(", 1)[1].split(")", 1)[0]
    initialized = set(file_block.split())
    for name in RETIRED_PROJECTIONS:
        assert name not in initialized, f"retired projection recreated: {name}_state.json"
        assert f'"$STATE_DIR/{name}_state.json"' in initializer, (
            f"retired projection is not explicitly purged: {name}_state.json"
        )

    monitor_source = "dashboard/workers/monitor_worker.sh"
    assert monitor_source not in aggregate


if __name__ == "__main__":
    main()
    print("dashboard state legacy retirement regression: OK")
