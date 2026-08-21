# Agent-owned Instance Runtime

## Objetivo

O Controller mantém política, placement e autorização. O Agent proprietário mantém a identidade operacional local da instância e executa observações/ações por meio de contratos estruturados. O Controller nunca envia shell arbitrário.

## B6 foundation

A foundation introduziu identidade local, inventário, `status`, `doctor`, fila persistente Controller→Agent, ownership e idempotência por `command_id`.

## B7 — Instance Runtime Adapters

A camada mutável é separada da observacional por adapters game-agnostic. O primeiro adapter é `systemd`; ele implementa `status`, `doctor`, `start`, `stop` e `restart`.

Nenhum adapter recebe argv, script ou nome de unit vindo do Controller. Para `adapter=systemd`, a unit é sempre derivada localmente:

```text
capivara-instance-<instance-id>.service
```

## B8 — Instance Service Provisioning

B8 define quem cria, reconcilia e remove a identidade de serviço consumida pelo B7. O processo normal é:

```text
Controller -> provisioning job -> heartbeat -> Agent request file
          -> privileged provisioner -> systemd unit -> result
          -> heartbeat -> Controller
```

O daemon principal continua executando como `capivara-agent`. Ele não recebe permissão para escrever em `/etc/systemd/system`. O pedido estruturado é gravado em `instance-provisioning/requests`; um serviço `root` acionado por `capivara-agent-instance-provisioner.path` faz somente a materialização privilegiada e grava o resultado no state dir do Agent.

A identidade local em `instances/<instance-id>.json` é criada ou atualizada somente depois que o resultado privilegiado é `completed`. Remoção retira a unit e a identidade operacional, mas preserva os dados da instância.

### Contrato administrativo

O endpoint administrativo é:

```text
POST /api/instances/provisioning
GET  /api/instances/provisioning?job_id=...
```

Para `provision` e `reconcile`, a entrada externa identifica `agent_id`, `instance_id`, `action` e `runtime_id`. O cliente não envia `ExecStart`, unit, shell ou argv livre. O Controller resolve `runtime_id` em `catalog/v2/runtimes`, valida a `RuntimeDefinition` e produz um launch profile normalizado.

O Agent revalida novamente o profile. B8 admite explicitamente apenas engines `native` e `java`:

- `native`: o artefato declarado pelo catálogo precisa existir no game-data e ser executável;
- `java`: o artefato é tratado como JAR e o Agent resolve seu próprio `java`, gerando `java -jar <artefato> ...` localmente.

O nome da unit nunca faz parte da autoridade remota. Ele continua derivado de `instance_id`.

### Unit e rollback

Antes de substituir uma unit, o provisioner usa `systemd-analyze verify`. A escrita é atômica e o conteúdo anterior é preservado para rollback caso a troca ou `daemon-reload` falhe. `reconcile` não altera uma unit ativa quando o conteúdo calculado mudou; a instância precisa ser parada primeiro. A remoção também preserva/restaura a unit em caso de falha de reload.

O unit file roda o servidor como `capivara-agent`, não como root, e mantém `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` e `ProtectHome=true`.

### Estado de provisioning

Uma identidade concluída recebe `provisioning_status=ready`. O Instance Runtime recusa `start`, `stop` ou `restart` de registros que possuam estado de provisioning diferente de `ready`.

## Identidade local e CLI

O Agent mantém registros em `CAPIVARA_AGENT_STATE_DIR/instances/<instance-id>.json` (padrão `/var/lib/capivara-agent`). Somente registros cujo `agent_id` coincide com a identidade local podem ser consultados ou operados.

```text
cap instance list
cap instance status <instance>
cap instance doctor <instance>
cap instance start <instance>
cap instance stop <instance>
cap instance restart <instance>
```

`list`, `status` e `doctor` permanecem observacionais. `start`, `stop` e `restart` passam por `cap_dispatch.py`, tornando explícita a fronteira mutável.

## Segurança

- allowlists explícitas de ações, adapters e launch engines;
- nenhum shell, `ExecStart`, nome de unit ou caminho absoluto de executável é aceito do Controller;
- runtime externo é referenciado por `runtime_id` e resolvido no catálogo versionado do Controller;
- artefato do jogo precisa permanecer dentro do game-data registrado no Agent;
- unit systemd é derivada exclusivamente de `instance_id`;
- ownership é validado no Controller e novamente no Agent;
- resultados precisam corresponder ao job/comando, instance e action originais;
- arquivos de estado são escritos atomicamente com modo `0600`;
- escrita de unit e `daemon-reload` ficam em provisioner root separado;
- o processo do jogo continua executando como usuário `capivara-agent`;
- falhas de provisioning não derrubam o heartbeat de liveness.

## Limite atual da B8

B8 resolve a **identidade de serviço** e o launch profile, mas não implementa ainda uma estratégia universal de materialização isolada de todo o game-data em `serverfiles` por instância. O artefato executável/JAR é validado no game-data gerenciado pelo Agent e a instância mantém seu diretório persistente separado. Estratégias como cópia completa, reflink, hardlink, overlay ou layout específico de runtime devem ser definidas em uma etapa própria, porque seus requisitos variam por jogo.

Da mesma forma, argumentos derivados de recursos alocados dinamicamente, como templates de portas (`-port={game}`), precisam ser materializados pela integração runtime/network antes de considerar o provisioning de um jogo específico completamente encerrado.

## Evolução

Adapters adicionais só devem ser adicionados quando houver uma necessidade real de mecanismo diferente de systemd. A próxima evolução natural após B8 é a materialização isolada de serverfiles/configuração por runtime e a expansão segura dos parâmetros de rede reservados.
