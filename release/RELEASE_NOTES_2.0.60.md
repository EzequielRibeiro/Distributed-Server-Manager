# Capivara DSM 2.0.60

Maintenance release focused on customer placement geography and server configuration administration.

## Highlights

- Customer placement now exposes the selected Datacenter geography as country, state/province and city, with flag, estimated latency and recommendation label in the server selector.
- Controller administration gains Region and Datacenter creation/editing, including geographic metadata and active/disabled state, while Controller role remains read-only.
- Baseline v11 adds `country_name`, `state_code` and `state_name` to Datacenters across SQLite, PostgreSQL, MySQL and MariaDB, with an additive upgrade path from existing installations.
- Initial Controller/Hybrid bootstrap can persist the same Datacenter geography metadata during installation.
- Customer server settings administration from PR #558 is included in the same release line.
- Release/update regression fixtures now derive pending baseline upgrades from the registry, avoiding hardcoded latest-upgrade versions.

## Included changes

- PR #555 — enrich placement geography and add Region/Datacenter administration.
- PR #558 — manage customer server configuration.

## Compatibility and upgrade notes

- Database migration Baseline v11 is additive and is applied through the canonical migration/update flow.
- Upgrade through the canonical `cap update` flow; no manual edits under `/opt/dsm` are required.
- Controllers on v2.0.59 must upgrade to v2.0.60 to receive the new placement frontend assets; the v2.0.59 release predates PR #555.
