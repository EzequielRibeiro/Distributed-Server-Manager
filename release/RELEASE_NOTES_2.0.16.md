# Capivara DSM 2.0.16

## Release focus

This release candidate hardens Windows Agent installation and OpenSSH bootstrap after field testing on a clean Windows 11 host, while preserving the Windows telemetry and runtime parity improvements accumulated in the 2.0 line.

## Windows Agent installation

- Removes `python -c` from `install-agent.ps1` to avoid quoting corruption observed through the Windows OpenSSH/PowerShell execution path.
- Executes package validation and local identity generation through temporary UTF-8 Python files with cleanup.
- Preserves manifest and SHA-256 validation for the full Windows Agent package.
- Keeps recursive Windows runtime packaging for Python, PowerShell and command files.

## Remote OpenSSH bootstrap

- Resolves `latest` to a concrete stable Agent release before remote bootstrap.
- Requires an explicit Windows bootstrap success marker.
- Performs post-install verification of `runtime/agent.py`, `agent.json` and Scheduled Task `CapivaraAgent`.
- Refuses false-positive bootstrap completion when the remote PowerShell process exits without a confirmed installation.
- Detects existing Windows Agents using the current `CapivaraAgent` installation paths instead of legacy `ProgramData\Capivara\Agent` paths.
- Keeps Pairing Tokens out of SSH argv and administrator-facing error messages.

## Windows observability

- Publishes host and Agent-process telemetry for CPU, RAM, disk, network and uptime.
- Includes disk throughput/IOPS and Processor Queue Length where available.
- Keeps temperature collection best-effort through Windows ACPI interfaces.
- Preserves distributed Storage Pool telemetry and Windows default Storage Pool creation.

## Compatibility

- Controller and Agent release candidate version: 2.0.16
- Linux Agent package: `capivara-agent-linux-2.0.16.tar.gz`
- Windows Agent package: `capivara-agent-windows-2.0.16.zip`

## Validation status

- Package download, checksum, extraction and 61-file Windows manifest verification were validated on Windows 11 during diagnosis of v2.0.15.
- Python 3.13, administrative privileges, local identity generation and Scheduled Task execution as SYSTEM were validated on the clean Windows 11 test host.
- Dashboard Remote Agent Install, Windows Agent Parity, External Controller Agent E2E and release-readiness CI gates passed on the source branch before candidate preparation.
- Final Windows 11 installation/enrollment validation is still required before this candidate is authorized or published.
