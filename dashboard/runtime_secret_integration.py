#!/usr/bin/env python3
"""Install runtime-secret transport on the existing authenticated configuration exchange."""
from __future__ import annotations

from configuration_repository import ConfigurationRepository
from runtime_secret_repository import RuntimeSecretOutbox

_NAMESPACE = "capivara.runtime.secret"
_INSTALLED = False


def install_runtime_secret_transport() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    original_desired = ConfigurationRepository.desired_for_agent
    original_record = ConfigurationRepository.record_agent_state

    def desired_for_agent(self, agent_id):
        commands = list(original_desired(self, agent_id))
        commands.extend(RuntimeSecretOutbox(self.backend).commands_for_agent(str(agent_id)))
        return commands

    def record_agent_state(self, agent_id, reports):
        values = [dict(item) for item in reports if isinstance(item, dict)] if isinstance(reports, list) else []
        secret_reports = [item for item in values if str(item.get("namespace") or "").strip().lower() == _NAMESPACE]
        normal_reports = [item for item in values if str(item.get("namespace") or "").strip().lower() != _NAMESPACE]
        RuntimeSecretOutbox(self.backend).apply_reports(str(agent_id), secret_reports)
        return original_record(self, agent_id, normal_reports)

    ConfigurationRepository.desired_for_agent = desired_for_agent
    ConfigurationRepository.record_agent_state = record_agent_state
    _INSTALLED = True


__all__ = ["install_runtime_secret_transport"]
