"""Best-effort Agent-owned GeoIP observation, cached to protect the heartbeat."""
from __future__ import annotations

import ipaddress
import os
import re
import time
import urllib.parse
import urllib.request
import json
from typing import Any

_CACHE: dict[str, Any] = {"ip": None, "expires": 0.0, "result": None}
_SUCCESS_TTL = 24 * 3600
_FAILURE_TTL = 3600


def _public_ip(value: Any) -> str | None:
    try:
        parsed = ipaddress.ip_address(str(value or ""))
        return str(parsed) if parsed.version == 4 and parsed.is_global else None
    except ValueError:
        return None


def _clean(value: Any, length: int = 100) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()[:length]


def _coordinate(value: Any, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
        return number if number == number and minimum <= number <= maximum else None
    except (ValueError, TypeError):
        return None


def _lookup(ip: str, *, timeout: float) -> dict[str, Any] | None:
    if os.environ.get("CAPIVARA_AGENT_GEOIP_ENABLED", "1") == "0":
        return None
    url = "https://ipwho.is/" + urllib.parse.quote(ip, safe="")
    request = urllib.request.Request(url, headers={"User-Agent": "Capivara-Agent/2 GeoIP"})
    with urllib.request.urlopen(request, timeout=max(1, min(float(timeout), 8))) as response:
        data = json.loads(response.read(4096))
    if not isinstance(data, dict) or data.get("success") is not True:
        return None
    country = _clean(data.get("country_code"), 2).upper()
    state = _clean(data.get("region_code"), 16).upper()
    if not re.fullmatch(r"[A-Z]{2}", country) or not re.fullmatch(r"[A-Z0-9-]{1,16}", state):
        return None
    return {
        "status": "observed",
        "public_ipv4": ip,
        "source": "ipwho.is",
        "kind": "geoip_estimated",
        "country_code": country,
        "country_name": _clean(data.get("country"), 100),
        "state_code": state,
        "state_name": _clean(data.get("region"), 100),
        "city": _clean(data.get("city"), 100),
        "latitude": _coordinate(data.get("latitude"), -90, 90),
        "longitude": _coordinate(data.get("longitude"), -180, 180),
    }


def observe_host_geolocation(public_ipv4_observation: dict[str, Any] | None, *, timeout: float = 3) -> dict[str, Any]:
    """The Agent reports its *own* geographic estimate, never the Controller's."""
    observation = public_ipv4_observation if isinstance(public_ipv4_observation, dict) else {}
    ip = _public_ip(observation.get("public_ipv4")) if observation.get("status") == "observed" else None
    if ip is None:
        return {"status": "unavailable"}
    now = time.monotonic()
    if _CACHE["ip"] == ip and now < _CACHE["expires"]:
        return dict(_CACHE["result"])
    try:
        result = _lookup(ip, timeout=timeout) or {"status": "unavailable"}
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        result = {"status": "unavailable"}
    _CACHE.update(ip=ip, result=result, expires=now + (_SUCCESS_TTL if result["status"] == "observed" else _FAILURE_TTL))
    return dict(result)


__all__ = ["observe_host_geolocation"]
