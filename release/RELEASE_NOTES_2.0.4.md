# Capivara DSM 2.0.4

## Agent prerequisites

- Reports whether SteamCMD is missing, installed with an error, or functioning.
- Allows an administrator to install and validate SteamCMD remotely from the Agent card.
- Stores the managed SteamCMD installation under the Agent state directory.
- Prevents Steam game-data jobs from starting while SteamCMD is unavailable.

## Dashboard

- Shows the SteamCMD state directly on every Agent card.
- Provides automatic progress and detailed errors for SteamCMD installation.
- Enforces the same prerequisite check in the catalog and in the Controller API.
