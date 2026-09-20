#!/usr/bin/env python3
"""Backend-neutral time-series persistence for Universal Observability."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from alert_repository import AlertSession
from observability_platform import ObservabilityValidationError, normalize_sample, utc_now

HISTORY_INTERVAL_SECONDS = max(60, min(int(os.environ.get("DSM_OBSERVABILITY_HISTORY_INTERVAL_SECONDS", "300")), 3600))
CHANGE_ONLY_METRICS = {
    "memory.total_bytes",
    "disk.root.total_bytes",
    "capivara.host.memory.total_bytes",
    "capivara.host.disk.total_bytes",
    "capivara.agent.pid",
}


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


class ObservabilityRepository:
    def __init__(self, backend, *, history_interval_seconds: int = HISTORY_INTERVAL_SECONDS):
        self.backend = backend
        self.history_interval_seconds = max(60, min(int(history_interval_seconds), 3600))

    def initialize(self) -> None:
        self.backend.initialize()

    @property
    def ph(self) -> str:
        return "?" if self.backend.name == "sqlite" else "%s"

    @staticmethod
    def _subject_key(sample: Mapping[str, Any]) -> str:
        return str(sample.get("instance_id") or "@agent")

    @staticmethod
    def _dimensions_json(sample: Mapping[str, Any]) -> str:
        return json.dumps(sample.get("dimensions") or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _dimensions_key(dimensions_json: str) -> str:
        return hashlib.sha256(dimensions_json.encode("utf-8")).hexdigest()

    @staticmethod
    def _row(row) -> dict[str, Any]:
        value = dict(row)
        try:
            value["dimensions"] = json.loads(value.pop("dimensions_json"))
        except (TypeError, json.JSONDecodeError):
            value["dimensions"] = {}
        if "value_double" in value:
            value["value"] = float(value.pop("value_double"))
        return value

    def _instance_owned(self, session: AlertSession, agent_id: str, instance_id: str) -> bool:
        row = session.execute(f"SELECT id FROM instances WHERE id={self.ph} AND agent_id={self.ph}", (instance_id, agent_id)).fetchone()
        return row is not None

    def _history_sample_id(self, sample: Mapping[str, Any], dimensions_key: str) -> str:
        instant = _parse_instant(str(sample["collected_at"]))
        bucket_epoch = int(instant.timestamp()) // self.history_interval_seconds * self.history_interval_seconds
        material = {
            "agent_id": str(sample["agent_id"]),
            "subject_key": self._subject_key(sample),
            "metric_name": str(sample["metric_name"]),
            "metric_type": str(sample["metric_type"]),
            "unit": str(sample["unit"]),
            "dimensions_key": dimensions_key,
            "bucket_epoch": bucket_epoch,
        }
        return "hist-" + hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _unchanged(latest: Mapping[str, Any] | None, sample: Mapping[str, Any], dimensions_json: str) -> bool:
        if latest is None:
            return False
        value = dict(latest)
        try:
            same_value = float(value["value_double"]) == float(sample["value"])
        except (KeyError, TypeError, ValueError):
            return False
        return (
            same_value
            and str(value.get("unit") or "") == str(sample["unit"])
            and str(value.get("metric_type") or "") == str(sample["metric_type"])
            and str(value.get("dimensions_json") or "{}") == dimensions_json
        )

    def ingest_agent_samples(self, agent_id: str, raw_samples: list[Mapping[str, Any]]) -> dict[str, Any]:
        accepted = created = rejected = 0
        accepted_ids: list[str] = []
        errors: list[dict[str, str]] = []
        now = utc_now()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                for raw in raw_samples[:2000]:
                    try:
                        sample = normalize_sample(raw, authenticated_agent_id=agent_id)
                        if sample.get("instance_id") and not self._instance_owned(session, agent_id, str(sample["instance_id"])):
                            raise ObservabilityValidationError("instance is not owned by authenticated Agent")
                    except (ObservabilityValidationError, ValueError) as exc:
                        rejected += 1
                        errors.append({"sample_id": str((raw or {}).get("sample_id") or ""), "error": str(exc)[:500]})
                        continue
                    accepted += 1
                    accepted_ids.append(sample["sample_id"])
                    dimensions_json = self._dimensions_json(sample)
                    subject_key = self._subject_key(sample)
                    dimensions_key = self._dimensions_key(dimensions_json)
                    latest = session.execute(
                        f"SELECT sample_id,value_double,unit,metric_type,dimensions_json,collected_at FROM observability_latest WHERE agent_id={self.ph} AND subject_key={self.ph} AND metric_name={self.ph} AND dimensions_key={self.ph}",
                        (agent_id, subject_key, sample["metric_name"], dimensions_key),
                    ).fetchone()

                    change_only = str(sample["metric_name"]) in CHANGE_ONLY_METRICS
                    persist_history = not (change_only and self._unchanged(latest, sample, dimensions_json))
                    history_sample_id = (
                        sample["sample_id"]
                        if change_only
                        else self._history_sample_id(sample, dimensions_key)
                    )
                    if persist_history:
                        exists = session.execute(
                            f"SELECT sample_id FROM observability_samples WHERE sample_id={self.ph}",
                            (history_sample_id,),
                        ).fetchone()
                        if not exists:
                            session.execute(
                                f"INSERT INTO observability_samples(sample_id,agent_id,instance_id,scope_type,metric_name,metric_type,value_double,unit,dimensions_json,collected_at,ingested_at) VALUES ({','.join([self.ph]*11)})",
                                (history_sample_id, agent_id, sample.get("instance_id"), sample["scope_type"], sample["metric_name"], sample["metric_type"], sample["value"], sample["unit"], dimensions_json, sample["collected_at"], now),
                            )
                            created += 1

                    values = (sample["sample_id"], sample["value"], sample["unit"], sample["metric_type"], dimensions_json, sample["collected_at"], now)
                    if latest is None:
                        session.execute(
                            f"INSERT INTO observability_latest(agent_id,subject_key,metric_name,dimensions_key,sample_id,value_double,unit,metric_type,dimensions_json,collected_at,updated_at) VALUES ({','.join([self.ph]*11)})",
                            (agent_id, subject_key, sample["metric_name"], dimensions_key, *values),
                        )
                    elif str(latest["collected_at"]) <= str(sample["collected_at"]):
                        session.execute(
                            f"UPDATE observability_latest SET sample_id={self.ph},value_double={self.ph},unit={self.ph},metric_type={self.ph},dimensions_json={self.ph},collected_at={self.ph},updated_at={self.ph} WHERE agent_id={self.ph} AND subject_key={self.ph} AND metric_name={self.ph} AND dimensions_key={self.ph}",
                            (*values, agent_id, subject_key, sample["metric_name"], dimensions_key),
                        )
            finally:
                session.close()
        return {"accepted": accepted, "created": created, "rejected": rejected, "accepted_sample_ids": accepted_ids, "errors": errors[:100]}

    def history(self, *, agent_id: str | None = None, instance_id: str | None = None, metric_name: str | None = None, since: str | None = None, until: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("agent_id", agent_id), ("instance_id", instance_id), ("metric_name", metric_name)):
            if value:
                clauses.append(f"{column}={self.ph}")
                params.append(value)
        if since:
            clauses.append(f"collected_at>={self.ph}")
            params.append(since)
        if until:
            clauses.append(f"collected_at<={self.ph}")
            params.append(until)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 5000)))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(f"SELECT * FROM observability_samples{where} ORDER BY collected_at DESC LIMIT {self.ph}", tuple(params)).fetchall()
                return [self._row(row) for row in rows]
            finally:
                session.close()

    def latest(self, *, agent_id: str | None = None, instance_id: str | None = None, metric_name: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id:
            clauses.append(f"agent_id={self.ph}"); params.append(agent_id)
        if instance_id:
            clauses.append(f"subject_key={self.ph}"); params.append(instance_id)
        if metric_name:
            clauses.append(f"metric_name={self.ph}"); params.append(metric_name)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 5000)))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(f"SELECT * FROM observability_latest{where} ORDER BY collected_at DESC LIMIT {self.ph}", tuple(params)).fetchall()
                result = []
                for row in rows:
                    item = self._row(row)
                    subject_key = item.pop("subject_key")
                    item["instance_id"] = None if subject_key == "@agent" else subject_key
                    item.pop("dimensions_key", None)
                    result.append(item)
                return result
            finally:
                session.close()

    def summary(self, **filters: Any) -> list[dict[str, Any]]:
        rows = self.history(**filters)
        grouped: dict[tuple[str, str | None, str, str], list[float]] = {}
        units: dict[tuple[str, str | None, str, str], str] = {}
        for row in rows:
            dimensions_key = json.dumps(row.get("dimensions") or {}, sort_keys=True, separators=(",", ":"))
            key = (str(row["agent_id"]), row.get("instance_id"), str(row["metric_name"]), dimensions_key)
            grouped.setdefault(key, []).append(float(row["value"]))
            units[key] = str(row.get("unit") or "1")
        result = []
        for key, values in sorted(grouped.items()):
            agent, instance, metric, dimensions_key = key
            result.append({"agent_id": agent, "instance_id": instance, "metric_name": metric, "dimensions": json.loads(dimensions_key), "unit": units[key], "count": len(values), "min": min(values), "max": max(values), "avg": sum(values) / len(values)})
        return result

    def count_before(self, before: str) -> int:
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT COUNT(*) AS total FROM observability_samples WHERE collected_at<{self.ph}",
                    (before,),
                ).fetchone()
                return int(dict(row).get("total") or 0) if row is not None else 0
            finally:
                session.close()

    def prune_before(self, before: str, *, limit: int | None = None) -> int:
        bounded = None if limit is None else max(1, min(int(limit), 50000))
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                if bounded is None:
                    cursor = session.execute(
                        f"DELETE FROM observability_samples WHERE collected_at<{self.ph}",
                        (before,),
                    )
                    return max(0, int(getattr(cursor, "rowcount", 0) or 0))
                rows = session.execute(
                    f"SELECT sample_id FROM observability_samples WHERE collected_at<{self.ph} ORDER BY collected_at LIMIT {self.ph}",
                    (before, bounded),
                ).fetchall()
                sample_ids = [str(dict(row)["sample_id"]) for row in rows]
                if not sample_ids:
                    return 0
                placeholders = ",".join([self.ph] * len(sample_ids))
                cursor = session.execute(
                    f"DELETE FROM observability_samples WHERE sample_id IN ({placeholders})",
                    tuple(sample_ids),
                )
                return max(0, int(getattr(cursor, "rowcount", 0) or 0))
            finally:
                session.close()


__all__ = ["ObservabilityRepository"]
