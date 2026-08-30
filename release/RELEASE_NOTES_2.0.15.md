# Capivara DSM 2.0.15

## Release focus

This release consolidates the current Capivara DSM 2.0 line and publishes updated Linux and Windows Agent packages required by the remote deployment pipeline.

## Agent deployment

- Fixes Linux Agent installation failure caused by invalid instance storage root validation present in the previous v2.0.14 Agent package.
- Publishes the current Linux Agent runtime and installer from the latest validated source.
- Publishes the current Windows Agent package with the latest runtime parity improvements.
- Includes Windows OpenSSH deployment hardening using PowerShell EncodedCommand transport.
- Includes batch Agent deployment support for mixed Linux and Windows inventories.
- Includes Agent identity, enrollment, heartbeat and remote deployment improvements.

## Infrastructure and operations

- Includes current Agent network inventory and port-pool support.
- Includes current Controller/Agent heartbeat and identity handling.
- Includes administrative observability and Controller service-topology improvements.
- Includes current PostgreSQL baseline and distributed runtime fixes.

## Compatibility

- Controller and Agent release version: 2.0.15
- Linux Agent package: capivara-agent-linux-2.0.15.tar.gz
- Windows Agent package: capivara-agent-windows-2.0.15.zip

## Validation

- Linux and Windows Agent artifacts build successfully from the same release commit.
- SHA-256 validation passes for both Agent packages.
- Linux Agent package no longer contains the invalid NUL storage-root validation that prevented installation in v2.0.14.
