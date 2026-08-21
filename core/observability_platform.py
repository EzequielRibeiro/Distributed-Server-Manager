#!/usr/bin/env python3
"""Canonical metric contract for Capivara Universal Observability."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping

_METRIC_RE = re.compile(r"^[a-z][a-z0-9_.]{1,126}[a-z0-9]$")
_SCOPE_TYPES = {"agent", "instance"}
_METRIC_TYPES = {"gauge", "counter"}


class ObservabilityValidationError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_sample(raw: Mapping[str, Any], *, authenticated_agent_id: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ObservabilityValidationError("metric sample must be an object")
    metric_name = str(raw.get("metric_name") or "").strip().lower()
    if not _METRIC_RE.fullmatch(metric_name):
        raise ObservabilityValidationError("invalid metric_name")
    scope_type = str(raw.get("scope_type") or "agent").strip().lower()
    if scope_type not in _SCOPE_TYPES:
        raise ObservabilityValidationError("invalid scope_type")
    agent_id = str(raw.get("agent_id") or authenticated_agent_id or "").strip()
    if not agent_id:
        raise ObservabilityValidationError("agent_id required")
    if authenticated_agent_id and agent_id != authenticated_agent_id:
        raise ObservabilityValidationError("Agent identity mismatch")
    instance_id = str(raw.get("instance_id") or "").strip() or None
    if scope_type == "instance" and not instance_id:
        raise ObservabilityValidationError("instance scope requires instance_id")
    if scope_type == "agent" and instance_id:
        raise ObservabilityValidationError("agent scope cannot include instance_id")
    metric_type = str(raw.get("metric_type") or "gauge").strip().lower()
    if metric_type not in _METRIC_TYPES:
        raise ObservabilityValidationError("invalid metric_type")
    try:
        value = float(raw.get("value"))
    except (TypeError, ValueError) as exc:
        raise ObservabilityValidationError("numeric value required") from exc
    if not math.isfinite(value):
        raise ObservabilityValidationError("value must be finite")
    unit = str(raw.get("unit") or "1").strip()[:32] or "1"
    dimensions = raw.get("dimensions") or {}
    if not isinstance(dimensions, Mapping):
        raise ObservabilityValidationError("dimensions must be an object")
    clean_dimensions = {str(k)[:64]: str(v)[:256] for k, v in dimensions.items() if str(k).strip()}
    collected_at = str(raw.get("collected_at") or utc_now()).strip()
    identity = {
        "agent_id": agent_id,
        "instance_id": instance_id,
        "metric_name": metric_name,
        "metric_type": metric_type,
        "value": value,
        "unit": unit,
        "dimensions": clean_dimensions,
        "collected_at": collected_at,
    }
    sample_id = str(raw.get("sample_id") or "").strip()
    if not sample_id:
        sample_id = hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "kind": "CapivaraMetricSample",
        "sample_id": sample_id[:191],
        "scope_type": scope_type,
        **identity,
    }


def normalize_batch(values: list[Mapping[str, Any]], *, authenticated_agent_id: str | None = None, limit: int = 2000) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise ObservabilityValidationError("metric batch must be a list")
    return [normalize_sample(item, authenticated_agent_id=authenticated_agent_id) for item in values[:limit]]


__all__ = ["ObservabilityValidationError", "normalize_batch", "normalize_sample", "utc_now"]
