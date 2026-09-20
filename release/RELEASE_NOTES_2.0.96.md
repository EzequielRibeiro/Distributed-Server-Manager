# Capivara DSM 2.0.96

Corrective release for the customer instance file browser, with Minecraft private-storage migration.

## Fixes

- Fixes the Minecraft "Arquivos da instância" root so it points to the instance-private runtime tree instead of the broader runtime-home.
- Existing Linux Minecraft Java and Bedrock instances migrate their runtime profile to expose `<instance_state_root>/runtime` as `files_root`.
- New Windows Minecraft Java instances also declare the private runtime tree as `files_root`.
- Shared provider `game-data` remains a seed/source and is not exposed as the customer's writable file root.
- Fixes storage usage display: the UI now consumes the Agent's canonical `usage_bytes` field, removing the false `— / quota` display.
- Displays the file-browser root as `/` instead of `.`.
- Fixes "Nova pasta" to create the requested child directory under the current path.
- Disables "Subir" while already at the file-browser root.

## Validation

- PR #723 passed all 37 GitHub workflow gates with 0 failures.
- Minecraft Java Runtime passed.
- Minecraft Bedrock Runtime passed.
- Hybrid Customer Workspace Parity passed.
- Customer Instance Workspace v2 passed.
- PostgreSQL, MySQL and MariaDB isolated baseline gates passed.
- Linux/Windows M10 Final E2E and External Controller-Agent E2E passed.
- CI passed.
- The live Horizon Minecraft unit was verified to use the private working directory:
  `/opt/dsm/runtime/hybrid-instance-storage/cli-000001-minecraft-001/runtime`.
