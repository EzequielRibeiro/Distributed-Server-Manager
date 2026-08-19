# Agent game-data library

## Contract

`game-data` is an Agent-local reusable library of validated dedicated-server bases. It is not a customer instance and no game process should execute directly from it.

The lifecycle is:

1. Resolve a runtime from the game catalog.
2. Resolve its provider (SteamCMD, HTTP archive, official API, or another provider).
3. Download/validate the dedicated-server base into the Agent's `game-data` location when it is not already ready.
4. Provision an instance by copying that validated base into `instances/<node>/<game>/<instance>/serverfiles`.
5. Execute only the instance copy.
6. Reinstall from `game-data` through staging and atomic replacement, optionally restoring instance-owned configuration/map persistence.

## Ownership

- Controller: knows which runtime/server bases are available on each Agent and may request prepare/verify/update operations.
- Agent: owns its local `game-data` storage and performs provider downloads/validation.
- Customer instance: owns its independent `serverfiles`, configuration, content and persistent game state.

## Isolation

Updating or replacing a base in `game-data` must never mutate an existing instance. Existing instances change only through an explicit update/reinstall operation.

## Current implementation audit

The current provisioning worker already follows the intended cache/library flow: it resolves `_game_data_directory`, checks `_game_data_ready`, invokes `installer/install_selection.sh` only when the base is absent/incomplete, and then copies the base into the instance `serverfiles`. The reinstall path likewise validates the base executable and stages a copy before replacing the instance files.

The dashboard terminology must therefore distinguish **preparing the server base on the Agent** from **installing/reinstalling the server in an instance**. Steam is a provider, not the UI concept.

## Multi-Agent inventory

Library inventory is per Agent. A future remote-Agent transport can aggregate entries with: Agent ID, runtime/game, provider, version/build, readiness and size. The Controller must not assume that a base available on one Agent exists on another.
