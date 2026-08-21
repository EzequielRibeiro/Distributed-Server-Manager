# Agent-owned Instance Runtime

## Objetivo

O Controller mantém política, placement e autorização. O Agent proprietário mantém a identidade operacional local da instância e executa observações/ações por meio de contratos estruturados. O Controller nunca envia shell arbitrário.

## B6 foundation

A primeira entrega limita o transporte remoto a ações observacionais:

- `status`
- `doctor`

Ações de lifecycle (`start`, `stop`, `restart`) ficam fora desta primeira entrega até existir uma interface de adapter genérica e testável.

## Identidade local

O Agent mantém registros em `CAPIVARA_AGENT_STATE_DIR/instances/<instance-id>.json` (padrão `/var/lib/capivara-agent`). Cada registro inclui obrigatoriamente `instance_id` e `agent_id`; campos como `game_id`, `environment_id`, `runtime_id`, `adapter`, `path`, `desired_state` e `observed_state` são game-agnostic.

Somente registros cujo `agent_id` coincide com a identidade local podem ser consultados.

## CLI

```text
cap instance list
cap instance status <instance>
cap instance doctor <instance>
```

No Agent essas operações são locais e read-only. Em instalação Controller, os subcomandos administrativos legados de `cap instance ...` permanecem no Controller. Em Hybrid, os três subcomandos acima usam a superfície local; os demais continuam administrativos.

## Transporte

O Controller persiste comandos em `agent_instance_commands`. O heartbeat entrega no máximo o próximo comando pendente:

```json
{
  "instance_command": {
    "command_id": "instance-cmd-...",
    "agent_id": "agent-...",
    "instance_id": "instance-...",
    "action": "doctor"
  }
}
```

O Agent persiste o resultado antes de reportá-lo. O histórico por `command_id` torna a execução idempotente: uma reentrega produz o mesmo resultado em vez de repetir a observação.

## Segurança

- allowlist estrita de ações; nesta fase somente `status` e `doctor`;
- nenhum argv, script ou comando shell é aceito do Controller;
- ownership é validado no Controller antes de enfileirar e novamente no Agent antes de observar;
- IDs usados como nomes de arquivo passam por validação de token;
- arquivos de estado são escritos atomicamente com modo `0600`;
- falhas do canal de Instance Runtime não derrubam o heartbeat de liveness.

## Próximas etapas

Lifecycle mutável só deve ser habilitado depois de uma interface `InstanceRuntimeAdapter` game-agnostic, com adapters explícitos (por exemplo systemd/native, Steam-based e Java) e contratos idempotentes de start/stop/restart.
