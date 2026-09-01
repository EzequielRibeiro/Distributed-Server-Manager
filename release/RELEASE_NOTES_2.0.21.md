# Capivara DSM 2.0.21

## Windows Agent

- Added host telemetry parity with Linux for CPU usage, memory, disk, network throughput, uptime, Agent process metrics, and top processes.
- Windows heartbeat now publishes the platform-neutral `telemetry` contract consumed by Controller observability and Agent detail widgets.
- Added a persistent Windows runtime log at `C:\ProgramData\CapivaraAgent\state\agent-runtime.log`.
- Recent Windows Agent runtime logs are published to the Controller through the existing `agent_logs` heartbeat field.
- Preserved the existing Windows remote-uninstall entrypoint lifecycle while adding telemetry and logging integration.

## Reliability

- Added a Windows telemetry contract test that verifies the collector, heartbeat integration, runtime logging, and recursive Windows package inclusion.
- Release validation now compiles the Windows telemetry modules and runs the new contract test before artifacts are published.

## Upgrade validation

After upgrading a Windows Agent to 2.0.21, verify that:

- the Agent remains `online` with its existing Agent ID and Node ID;
- `/api/agent/ports` exposes a populated `telemetry` object;
- observability history begins receiving `capivara.host.*` and `capivara.agent.*` metrics;
- the Agent details page renders CPU, RAM, disk, network, uptime, and process metrics;
- `C:\ProgramData\CapivaraAgent\state\agent-runtime.log` receives heartbeat entries.
