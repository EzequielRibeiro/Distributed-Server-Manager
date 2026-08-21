# Agent-owned Instance Runtime

## Objetivo

O Controller mantém política, placement e autorização. O Agent proprietário mantém a identidade operacional local da instância e executa observações/ações por meio de contratos estruturados. O Controller nunca envia shell arbitrário.

## B6 foundation

A foundation introduziu identidade local, inventário, `status`, `doctor`, fila persistente Controller→Agent, ownership e idempotência por `command_id`.

## B7 — Instance Runtime Adapters

A camada mutável é separada da observacional por adapters game-agnostic. O primeiro adapter é `systemd`; ele implementa `status`, `doctor`, `start`, `stop` e `restart`.

Nenhum adapter recebe argv, script ou nome de unit vindo do Controller.

## B8 — Instance Runtime Materialization

B8 separa explicitamente criação/configuração do runtime de seu controle operacional.

```text
Runtime Spec -> Materializer -> runtime local -> Adapter -> lifecycle/status
```

O contrato `CapivaraInstanceRuntimeSpec` é validado no Agent e contém somente campos estruturados: `instance_id`, `agent_id`, `runtime_id`, `adapter`, `working_directory`, `executable`, `arguments`, `environment`, `user` e `desired_state`. O materializador não aceita shell, unit name ou argv opaco fornecido como comando remoto.

O primeiro materializador é `SystemdMaterializer`. A unit continua sendo derivada exclusivamente do `instance_id`:

```text
capivara-instance-<instance-id>.service
```

A unit recebe marcadores locais de ownership (`X-Capivara-GeneratedBy`, `X-Capivara-Instance`, `X-Capivara-Agent` e `X-Capivara-Runtime`). Uma unit existente sem esses marcadores nunca é substituída ou removida. Escritas são atômicas e `daemon-reload` só ocorre quando há mudança real.

### Desired/observed reconciliation

A reconciliação compara `desired_state` com o estado observado pelo adapter:

```text
desired=running + observed=stopped -> start
desired=stopped + observed=running -> stop
estado já convergente              -> nenhuma mutação
```

Estados desejados iniciais são `running` e `stopped`. O reconciler opera apenas runtimes que existem e cujo ownership local foi validado pelo materializador.

### Eventos B8

O produtor local de runtime grava eventos estruturados para posterior ingestão pela Universal Event Platform:

- `INSTANCE_RUNTIME_MATERIALIZING`
- `INSTANCE_RUNTIME_READY`
- `INSTANCE_RUNTIME_FAILED`
- `INSTANCE_RUNTIME_RECONCILED`
- `INSTANCE_RUNTIME_IN_SYNC`
- `INSTANCE_RUNTIME_REMOVED`

Os eventos são persistidos em `CAPIVARA_AGENT_STATE_DIR/events/instance-runtime.jsonl` e não substituem o canal universal; funcionam como producer durável do Agent.

## Identidade local

O Agent mantém registros em `CAPIVARA_AGENT_STATE_DIR/instances/<instance-id>.json` (padrão `/var/lib/capivara-agent`). Cada registro inclui obrigatoriamente `instance_id` e `agent_id`; campos como `game_id`, `environment_id`, `runtime_id`, `adapter`, `path`, `desired_state` e `observed_state` são game-agnostic.

Somente registros cujo `agent_id` coincide com a identidade local podem ser consultados ou operados.

## CLI

```text
cap instance list
cap instance status <instance>
cap instance doctor <instance>
cap instance start <instance>
cap instance stop <instance>
cap instance restart <instance>
```

`list`, `status` e `doctor` permanecem observacionais. `start`, `stop` e `restart` passam por `cap_dispatch.py`, tornando explícita a fronteira mutável. Materialização e reconciliação não são expostas como shell remoto; são serviços internos do Agent destinados ao provisioning e, futuramente, aos Game Runtime Profiles da B9.

## Transporte

O Controller persiste comandos de lifecycle em `agent_instance_commands`. O heartbeat entrega no máximo o próximo comando pendente. O Agent persiste o resultado antes de reportá-lo. O histórico por `command_id` torna a execução idempotente: uma reentrega produz o mesmo resultado em vez de repetir a ação.

## SystemdAdapter

O `SystemdAdapter` executa somente uma allowlist fixa de operações. Antes e depois de lifecycle ele consulta `LoadState`, `ActiveState` e `SubState`; `start` de uma unit já ativa e `stop` de uma unit já inativa são tratados como sucesso idempotente.

A autorização do processo `capivara-agent` é restrita por policy local a units cujo nome corresponda a `capivara-instance-*.service` e aos verbos `start`, `stop` e `restart`. A policy não autoriza administração genérica de systemd.

## Segurança

- allowlist estrita de adapters e materializers;
- nenhum shell arbitrário é aceito do Controller;
- unit systemd derivada exclusivamente do `instance_id` local;
- runtime spec validada e vinculada ao Agent proprietário;
- materializer recusa sobrescrever/remover unit sem ownership Capivara verificável;
- ownership validado no Controller e novamente no Agent;
- IDs usados como nomes de arquivo passam por validação de token;
- arquivos de estado e eventos locais usam escrita restrita;
- lifecycle remoto não concede ao Agent autorização genérica para administrar services;
- falhas do canal de Instance Runtime não derrubam o heartbeat de liveness.

## Evolução

B9 deve introduzir Game Runtime Profiles que produzam `RuntimeSpec` a partir de contratos próprios de cada jogo. Isso mantém particularidades de DayZ, Minecraft, Arma e outros jogos fora do materializer e fora do `SystemdAdapter`.

Adapters/materializers adicionais só devem ser adicionados quando houver necessidade real de mecanismo diferente de systemd e devem entrar explicitamente nos respectivos registries.
