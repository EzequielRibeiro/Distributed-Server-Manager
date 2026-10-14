"""Validate Controller-stored Agent evidence results before lifecycle interpretation.

This is structural and scope validation, not transport authentication. The caller
must obtain the command from its trusted repository and bind it to the expected
Agent, instance, action, and requested time window. Never accept user event JSON.
"""
from dayz_native_transition import observed_systemd_restart

ACTION = 'systemd_lifecycle_evidence'

def authenticated_restart_observation(*, command, agent_id, instance_id, since, until):
    if not isinstance(command, dict):
        return False
    if (command.get('agent_id') != agent_id or
            command.get('instance_id') != instance_id or
            command.get('action') != ACTION or
            command.get('status') != 'completed'):
        return False
    parameters = command.get('parameters')
    if not isinstance(parameters, dict) or parameters.get('since') != since or parameters.get('until') != until:
        return False
    outer = command.get('result')
    if not isinstance(outer, dict):
        return False
    if (outer.get('command_id') != command.get('command_id') or
            outer.get('instance_id') != instance_id or
            outer.get('action') != ACTION or outer.get('status') != 'completed'):
        return False
    payload = outer.get('result')
    if not isinstance(payload, dict) or payload.get('agent_id') != agent_id:
        return False
    if payload.get('scope') != 'instance-local' or payload.get('schema_version') != 1:
        return False
    return observed_systemd_restart(instance_id=instance_id,expected_at=since,deadline_at=until,
                                     observations=payload,authenticated=True)
