# Instance Provisioning Pipeline — B10

## Objetivo

B10 conecta placement já concluído, reservas de rede, instalação de conteúdo, Game Runtime Profiles (B9) e materialização/reconciliação do runtime (B8) em uma operação persistente Controller → Agent.

O pipeline não escolhe Agent, não aloca portas no Agent e não aceita shell arbitrário. O Controller entrega intenção estruturada; o Agent proprietário valida novamente ownership e executa apenas contratos locais allowlisted.

## Fluxo

```text
Controller
  |
  | CapivaraInstanceProvisioningRequest
  v
Agent owner
  |
  +-> prepare workspace
  +-> validate reserved ports
  +-> install/update/verify content
  +-> GameRuntimeProfile -> RuntimeSpec
  +-> privileged materialization helper
  +-> initial desired/observed reconciliation
  v
completed / failed
```

## B10.1 — Provisioning Contract

`CapivaraInstanceProvisioningRequest` é versionado e contém `provisioning_id`, `agent_id`, `instance_id`, `environment_id`, `selector`, `desired_state`, `instance`, `content`, `ports` e `configuration`.

O Agent rejeita campos de configuração que tentem transportar autoridade de execução (`shell`, `command`, `argv`, `unit`, `service`).

## B10.2 — Operation identity

O Controller persiste cada operação em `agent_instance_provisioning`. Estados oficiais:

```text
queued -> delivered -> running -> completed
                            \----> failed
```

`current_step`, `progress`, timestamps, erro e resultado permanecem persistidos. Enquanto existe uma operação ativa para a instância, novo enqueue retorna a mesma operação em vez de duplicá-la.

## B10.3 — Controller → Agent

O heartbeat autenticado transporta no máximo a próxima operação ativa em `provisioning_command`. O Agent reporta `provisioning_result` no heartbeat seguinte. Falhas desse canal não derrubam o liveness do Agent.

## B10.4 — Workspace

O Agent prepara um workspace local sob `CAPIVARA_AGENT_STATE_DIR/instance-workspaces/<instance-id>` com áreas `staging`, `config` e `runtime`. IDs passam por validação e o path é confinado ao root local.

## B10.5 — Port binding

O Controller lê somente reservas já existentes em `instance_ports` e as incorpora ao contrato. O Agent valida número/protocolo e entrega essas reservas ao profile. Nenhum fallback escolhe outra porta silenciosamente.

## B10.6 — Content binding

O executor reutiliza o pipeline existente de game-data para `install`, `update` ou `verify`. O `target_path` produzido pela instalação torna-se o `install_path` autoritativo fornecido ao profile.

Enquanto um provisioning está ativo, o heartbeat não entrega simultaneamente um job game-data independente para o mesmo canal do Agent.

## B10.7 — Profile → RuntimeSpec

B9 continua sendo a única camada que conhece detalhes de jogo. B10 entrega `instance + content path + reserved ports + configuration` ao profile e recebe uma `CapivaraInstanceRuntimeSpec` validada.

## B10.8 — Materialization e initial reconciliation

O daemon `capivara-agent` continua não privilegiado. Como criação/remoção de unit em `/etc/systemd/system` requer root, B10 introduz uma fronteira dedicada:

```text
capivara-agent (unprivileged)
  |
  | structured request bound to instance_id + agent_id + RuntimeSpec
  v
capivara-agent-materialize@<instance-id>.service
  |
  | root, oneshot, narrow filesystem permissions
  v
SystemdMaterializer
```

A policy autoriza o usuário `capivara-agent` apenas a iniciar o template `capivara-agent-materialize@<token>.service`. O helper root lê a identidade real local, revalida ownership, revalida a RuntimeSpec e aceita somente `apply` ou `remove`.

O daemon principal permanece `User=capivara-agent`; ele não recebe privilégio genérico de escrita em `/etc/systemd/system`.

Após materializar, a reconciliação B8 converge `desired_state` para o estado observado usando o adapter.

## B10.9 — Failure e compensation

Se uma etapa falhar:

- runtime já materializado é removido por meio do helper privilegiado;
- staging é limpo quando possível;
- conteúdo instalado é preservado para retry;
- reservas de portas pertencentes ao Controller são preservadas;
- a operação termina `failed`, com `current_step`, erro e compensation registrados.

A política evita churn destrutivo e mantém evidência suficiente para retry/auditoria.

## B10.10 — Events, tests e CI

Eventos locais estruturados:

- `INSTANCE_PROVISIONING_STARTED`
- `INSTANCE_PROVISIONING_STEP`
- `INSTANCE_PROVISIONING_COMPLETED`
- `INSTANCE_PROVISIONING_FAILED`

O CI cobre contrato, ownership, reservas de portas, idempotência, transporte por heartbeat, progress, pipeline content→profile→materialization→reconcile, compensation, paridade de migrations, packaging e fronteira privilegiada.

## API administrativa

```text
POST /api/instances/provisioning
GET  /api/instances/provisioning?provisioning_id=<id>
```

A criação é restrita a `admin/controller` e exige uma instância já vinculada ao Agent e com reservas de portas existentes.

## Fronteiras preservadas

- Controller não envia shell;
- Agent não escolhe placement;
- Agent não inventa portas;
- content provider não conhece systemd;
- Game Runtime Profile não materializa units;
- materializer não conhece jogos;
- adapter não conhece provisioning;
- helper root não aceita unit name arbitrário nem comandos arbitrários.

## Próxima fase

B11 deve transformar a reconciliação pontual em reconciliação contínua e recuperação: reboot do Agent, drift, unit ausente, processo morto, reconnect do Controller e recovery de estados failed/stale.
