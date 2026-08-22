#!/usr/bin/env python3
from __future__ import annotations

import sys
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))

from json_response import install_json_safe_responses, json_safe


def main() -> int:
    payload = {
        "created_at": datetime(2026, 8, 22, 12, 50, 44, tzinfo=timezone.utc),
        "day": date(2026, 8, 22),
        "clock": time(12, 50, 44),
        "amount": Decimal("12.50"),
        "path": Path("/opt/dsm"),
        "id": UUID("12345678-1234-5678-1234-567812345678"),
        "nested": [{"updated_at": datetime(2026, 8, 22, 12, 51, 25)}],
    }
    normalized = json_safe(payload)
    assert normalized["created_at"] == "2026-08-22T12:50:44+00:00"
    assert normalized["day"] == "2026-08-22"
    assert normalized["clock"] == "12:50:44"
    assert normalized["amount"] == "12.50"
    assert normalized["path"] == "/opt/dsm"
    assert normalized["id"] == "12345678-1234-5678-1234-567812345678"
    assert normalized["nested"][0]["updated_at"] == "2026-08-22T12:51:25"

    calls = []
    class Handler:
        def send_json(self, code, value):
            calls.append((code, value))

    install_json_safe_responses(Handler)
    install_json_safe_responses(Handler)
    Handler().send_json(200, {"at": datetime(2026, 8, 22, 12, 0, 0)})
    assert calls == [(200, {"at": "2026-08-22T12:00:00"})]

    print("json_response_test: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
