# Phase 4 — Region, Datacenter and Agent Location

Status: implementation contract

Phase 4 closes the placement prerequisite that requires every usable Agent to belong to an active Agent Location, Datacenter and Region chain.

## Administrative hierarchy

```text
Region
  └── Datacenter
        └── Agent Location
              └── Agent
```

Placement remains fail-closed. A complete active geographic hierarchy is necessary in addition to an active Controller and Agent.

## Region

Administrators can create and edit Regions with:

- `id`;
- `name`;
- optional ISO-like two-letter `country_code`;
- `status` (`active` or `disabled`);
- optional `latitude` and `longitude`;
- optional `continent_code` retained by the existing schema.

Coordinates are never generated or inferred. Omission persists `NULL`.

Physical deletion is intentionally not part of the administrative contract. Disabling a Region removes its descendants from placement eligibility without destroying topology/history.

## Datacenter

Administrators can create and edit Datacenters with:

- `id`;
- required `region_id` referencing an existing Region;
- `name`;
- `status` (`active` or `disabled`);
- optional provider/city/country metadata already supported by the schema;
- optional coordinates.

A disabled Datacenter or disabled parent Region makes the chain ineligible for placement.

## Agent Location

Phase 4 reuses the existing modules:

- `database/location_repository.py`;
- `dashboard/agent_location_api.py`;
- `dashboard/agent_location_http.py`.

Agent Location coordinates and `public_host` remain optional. The Agent must point to an existing active Datacenter when an administrator/controller assigns its location.

## Administrative API modules

Region and Datacenter administration is isolated from the legacy dashboard server in:

- `dashboard/location_admin_api.py`;
- `dashboard/location_admin_http.py`.

Admin users may create/edit topology. Controller users may read topology so they can select valid Datacenters for their Agents. Customer users cannot access infrastructure topology administration.

The mutation endpoints use `status=disabled` instead of destructive deletion.

## Hybrid local topology

A fresh Hybrid installation creates a neutral local topology automatically:

```text
Local
  └── Local Default
        └── local Agent
```

This local bootstrap intentionally does not invent country, city, provider, latitude or longitude.

The administrator can later rename/reclassify it, for example:

```text
Brasil Sudeste
  └── Limeira / Horizon
        └── horizon-server
```

No coordinate is required for this transition.

## Placement invariant

An Agent is a placement candidate only when:

```text
Controller.status == active
AND Agent.status == active
AND Agent Location.status == active
AND Datacenter.status == active
AND Region.status == active
```

Changing any Region, Datacenter or Agent Location to `disabled` immediately removes the Agent from new-placement candidates.

## Phase boundary

Phase 4 provides persistence, validation, RBAC-aware administrative functions, transport-neutral HTTP dispatchers, Agent Location reuse and Hybrid neutral topology. It does not add map/geocoding behavior and does not require geographic coordinates.
