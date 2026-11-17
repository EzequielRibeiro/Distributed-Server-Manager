"""Authoritative separation of Controller location and Agent-reported geography.

The Agent reports an estimated location derived from its own public IP. The
Controller verifies the authenticated Agent, never copies Controller geography
into the Agent, and allows administrative overrides to take precedence.
"""
from __future__ import annotations

import ipaddress
import json
import re
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from location_repository import LocationRepository

_GEO_MODE_KEY = "capivara_location_mode"


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _valid_location(network: dict[str, Any]) -> dict[str, Any] | None:
    geo = network.get("geo_location_observation")
    ipv4 = network.get("public_ipv4_observation")
    if not isinstance(geo, dict) or not isinstance(ipv4, dict):
        return None
    if geo.get("status") != "observed" or ipv4.get("status") != "observed":
        return None
    if geo.get("kind") != "geoip_estimated" or geo.get("source") != "ipwho.is":
        return None
    try:
        ip = ipaddress.ip_address(str(ipv4.get("public_ipv4") or ""))
        if ip.version != 4 or not ip.is_global or str(ip) != str(geo.get("public_ipv4")):
            return None
    except ValueError:
        return None
    country = str(geo.get("country_code") or "").strip().upper()
    state = str(geo.get("state_code") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country) or not re.fullmatch(r"[A-Z0-9-]{1,16}", state):
        return None
    try:
        lat, lon = float(geo.get("latitude")), float(geo.get("longitude"))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
    except (TypeError, ValueError):
        return None
    def safe(value: Any) -> str:
        return re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()[:100]
    return dict(country=country,state=state,latitude=lat,longitude=lon,
                country_name=safe(geo.get("country_name")),state_name=safe(geo.get("state_name")),
                city=safe(geo.get("city")),public_ipv4=str(ip))


def sync_agent_reported_location(agent_id: str, network: dict[str, Any], *, backend) -> bool:
    """Map an authenticated Agent to its *own* verified GeoIP region.

    An explicit admin location takes precedence. No location is inherited
    from the Controller and existing instances are not modified.
    """
    report = _valid_location(network)
    if not report:
        return False
    repo = LocationRepository(backend)
    ph = dialect_for_backend(backend).placeholder
    with repo.session() as session:
        row = session.execute(
            "SELECT a.metadata_json,al.datacenter_id,al.latitude,al.longitude,al.public_host,"
            "al.status,d.country_code,d.state_code "
            "FROM agents a LEFT JOIN agent_locations al ON al.agent_id=a.id "
            "LEFT JOIN datacenters d ON d.id=al.datacenter_id "
            f"WHERE a.id={ph}", (agent_id,),
        ).fetchone()
    if row is None or _metadata(row["metadata_json"]).get(_GEO_MODE_KEY) == "manual":
        return False
    if (str(row["country_code"] or "").upper() == report["country"]
            and str(row["state_code"] or "").upper() == report["state"]):
        return False  # Already placed in the proper geographic area.

    region_id = "geo-" + report["country"].lower() + "-" + report["state"].lower()
    datacenter_id = "geo-" + agent_id
    repo.upsert_region(
        region_id=region_id,
        name=(report["country_name"] or report["country"]) + " - " + (report["state_name"] or report["state"]),
        country_code=report["country"],
        latitude=report["latitude"], longitude=report["longitude"],
    )
    repo.upsert_datacenter(
        datacenter_id=datacenter_id, region_id=region_id,
        name="Agent " + agent_id + " (GeoIP estimado)",
        city=report["city"],country_code=report["country"],
        country_name=report["country_name"],state_code=report["state"],
        state_name=report["state_name"],
        latitude=report["latitude"],longitude=report["longitude"],
    )
    repo.upsert_agent_location(
        agent_id=agent_id,datacenter_id=datacenter_id,
        latitude=report["latitude"],longitude=report["longitude"],
        public_host=row["public_host"],status=row["status"] or "active",
    )
    return True


def controller_location_for_agent(agent_id: str, *, backend) -> dict[str, Any] | None:
    """Controller geography, derived from the Controller node, not the remote Agent."""
    ph = dialect_for_backend(backend).placeholder
    with backend.connect() as connection:
        session = AlertSession(backend, connection)
        try:
            row = session.execute(
                "SELECT c.id AS controller_id,r.name AS region,r.country_code,d.city,"
                "d.state_name,d.state_code "
                "FROM agents a JOIN controllers c ON c.id=a.controller_id "
                "LEFT JOIN agents local ON local.node_id=c.node_id "
                "LEFT JOIN agent_locations al ON al.agent_id=local.id "
                "LEFT JOIN datacenters d ON d.id=al.datacenter_id "
                "LEFT JOIN regions r ON r.id=d.region_id "
                f"WHERE a.id={ph}", (agent_id,),
            ).fetchone()
        finally:
            session.close()
    if not row:
        return None
    return {"controller_id":str(row["controller_id"]),
            "region":row["region"],"country_code":row["country_code"],
            "state_code":row["state_code"],"state_name":row["state_name"],
            "city":row["city"]}


__all__ = ["sync_agent_reported_location", "controller_location_for_agent"]
