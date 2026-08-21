# Agent-owned Instance Runtime

## Objetivo

O Controller mantém política, placement e autorização. O Agent proprietário mantém a identidade operacional local da instância e executa observações/ações por meio de contratos estruturados. O Controller nunca envia shell arbitrário.

## B6 foundation

A foundation introduziu identidade local, inventário, `status`, `doctor`, fila persistente Controller→Agent, ownership e idempotência por `command_id`.

## B7 — Instance Runtime Adapters

A camada mutável é separada da observacional por adapters game-agnostic. O primeiro adapter é `systemd`; ele implementa:

- `status`
- `doctor`
- `start`
- `stop`
- `restart`

Nenhum adapter recebe argv, script ou nome de unit vindo do Controller.

## Identidade local

O Agent mantém registros em `CAPIVARA_AGENT_STATE_DIR/instances/<instance-id>.json` (padrão `/var/lib/capivara-agent`). Cada registro inclui obrigatoriamente `instance_id` e `agent_id`; campos como `game_id`, `environment_id`, `runtime_id`, `adapter`, `path`, `desired_state` e `observed_state` são game-agnostic.

Somente registros cujo `agent_id` coincide com a identidade local podem ser consultados ou operados.

Para `adapter=systemd`, a unit não é configurável remotamente. Ela é sempre derivada localmente:

```text
capivara-instance-<instance-id>.service
```

## CLI

```text
cap instance list
cap instance status <instance>
cap instance doctor <instance>
cap instance start <instance>
cap instance stop <instance>
cap instance restart <instance>
```

`list`, `status` e `doctor` permanecem observacionais. `start`, `stop` e `restart` passam por `cap_dispatch.py`, tornando explícita a fronteira mutável. Como `agent.json` permanece protegido em `0600`, operações locais de lifecycle podem exigir `sudo`; o Agent daemon usa uma autorização restrita própria.

## Transporte

O Controller persiste comandos em `agent_instance_commands`. O heartbeat entrega no máximo o próximo comando pendente:

```json
{
  "instance_command": {
    "command_id": "instance-cmd-...",
    "agent_id": "agent-...",
    "instance_id": "instance-...",
    "action": "restart"
  }
}
```

O Agent persiste o resultado antes de reportá-lo. O histórico por `command_id` torna a execução idempotente: uma reentrega produz o mesmo resultado em vez de repetir a ação.

## SystemdAdapter

O `SystemdAdapter` executa somente uma allowlist fixa de operações. Antes e depois de lifecycle ele consulta `LoadState`, `ActiveState` e `SubState`; `start` de uma unit já ativa e `stop` de uma unit já inativa são tratados como sucesso idempotente.

A autorização do processo `capivara-agent` é restrita por policy local a units cujo nome corresponda a `capivara-instance-*.service` e aos verbos `start`, `stop` e `restart`. A policy não autoriza administração genérica de systemd.

## Segurança

- allowlist estrita de ações e adapters;
- nenhum argv, script ou comando shell é aceito do Controller;
- unit systemd derivada exclusivamente do `instance_id` local;
- ownership validado no Controller e novamente no Agent;
- resultado remoto deve corresponder a `command_id + instance_id + action`;
- IDs usados como nomes de arquivo passam por validação de token;
- arquivos de estado são escritos atomicamente com modo `0600`;
- lifecycle remoto não concede ao Agent autorização genérica para administrar services;
- falhas do canal de Instance Runtime não derrubam o heartbeat de liveness.

## Evolução

Adapters adicionais só devem ser adicionados quando houver uma necessidade real de mecanismo diferente de systemd. Eles devem implementar `InstanceRuntimeAdapter`, entrar explicitamente no registry e manter a mesma separação entre intenção remota e autoridade local.
