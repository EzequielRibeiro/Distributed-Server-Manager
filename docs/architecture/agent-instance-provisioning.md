# Agent-owned Instance Service Provisioning

## Objetivo

A B8 liga o placement/provisioning do Controller ao Instance Runtime do Agent. O Controller escolhe a instância, o Agent e um `runtime_id` confiável do catálogo; o Agent proprietário materializa diretórios e uma unit systemd determinística antes de liberar lifecycle.

O Controller não envia `ExecStart`, nome de unit, shell ou argv arbitrário.

## Fluxo

```text
Controller
  -> resolve RuntimeDefinition do catalog
  -> enqueue provision/reconcile/remove
  -> heartbeat autenticado
Agent
  -> valida ownership local do comando
  -> grava request 0600
  -> systemd path aciona provisioner root
Provisioner
  -> valida contrato novamente
  -> consulta game-data instalado localmente
  -> resolve artefato dentro do game-data
  -> materializa argv por engine permitida
  -> prepara instance-data/<instance>/serverfiles
  -> renderiza e valida capivara-instance-<instance>.service
  -> escreve unit atomicamente + daemon-reload
  -> persiste resultado
Agent
  -> aplica registro local somente após sucesso
  -> reporta resultado no heartbeat
Controller
  -> conclui o job
```

## Contrato do Controller

Para `provision` e `reconcile`, a API administrativa recebe `agent_id`, `instance_id` e `runtime_id`. O launch profile é derivado do `RuntimeDefinition` existente em `catalog/v2/runtimes`; conteúdo de processo fornecido pelo cliente não é aceito como fonte de autoridade.

A fila persistente `agent_instance_provisioning_jobs` admite somente `provision`, `reconcile` e `remove`. Há no máximo um job `queued`/`delivered` por instância. Ownership é validado no Controller antes de enfileirar e o Agent valida novamente `agent_id` ao receber o comando.

## Launch profiles

B8 possui materializadores explícitos para `process.engine=native` e `process.engine=java`.

No modo `native`, o artefato do catálogo deve estar dentro do game-data local e possuir permissão de execução. O Agent gera `argv=[artefato, ...argumentos]`.

No modo `java`, o artefato — por exemplo `server.jar` — também precisa permanecer dentro do game-data local. O Agent localiza sua própria JVM com `java`, resolve o caminho real e gera `argv=[java, -jar, artefato, ...argumentos]`. O Controller não fornece o caminho da JVM nem o token `-jar`.

Engines fora da allowlist falham fechadas. Nenhum materializador usa `/bin/sh -c`.

## Layout local

```text
/var/lib/capivara-agent/
  instance-data/<instance-id>/serverfiles/
  instances/<instance-id>.json
  instance-provisioning/
    requests/<job-id>.json
    results/<job-id>.json
    history/<job-id>.json
```

A unit correspondente é sempre `/etc/systemd/system/capivara-instance-<instance-id>.service`. O nome é derivado localmente; qualquer campo `unit` vindo de fora é irrelevante para a materialização.

## Unit systemd

A unit executa como `capivara-agent`, usa `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome=true` e concede escrita somente à raiz de dados da própria instância. `systemd-analyze verify` valida uma cópia candidata antes da instalação.

Tokens, caminhos relativos e caracteres de controle passam por validações tanto no Controller quanto no Agent. O artefato resolvido deve permanecer dentro da raiz de game-data instalada localmente.

## Estados e lifecycle

O registro local inclui `provisioning_status`. `start` e `restart` só são permitidos quando o estado é `ready`; `stop` permanece possível como operação de segurança.

Estados reconhecidos localmente: `pending`, `provisioning`, `ready`, `failed`, `removing` e `unconfigured`. Instâncias antigas sem estado B8 são tratadas como `unconfigured` e devem ser reconciliadas antes de `start`/`restart`.

## Reconcile

`reconcile` é determinístico. Se o conteúdo calculado da unit já for igual ao instalado, nenhuma troca é feita. Se a unit precisar mudar enquanto a instância estiver ativa, o job falha e exige que a instância seja parada antes da reconciliação.

## Remove

`remove` interrompe a unit quando necessário, remove somente a definição de serviço e executa `daemon-reload`. Os dados da instância são preservados deliberadamente. O registro local é removido somente depois que o resultado privilegiado foi concluído com sucesso.

## Rollback e idempotência

A escrita da unit mantém a versão anterior e restaura o arquivo se `daemon-reload` falhar. A remoção também preserva a unit anterior e tenta restaurar seu estado ativo se a transação falhar. O histórico por `job_id` é durável: reprocessar um job finalizado reutiliza o resultado anterior em vez de repetir a operação privilegiada.

## Upgrade do Agent

O pacote Linux contém o provisioning client, o provisioner root e as units `capivara-agent-instance-provisioner.service/.path`. O updater os instala dentro da transação rollback-safe e habilita a path unit após validar os arquivos. Em falha, restaura arquivos e o estado anterior da path unit.

## Fora do escopo da B8

- substituição dinâmica de argumentos de rede/portas do catálogo;
- cópia completa de game-data por instância;
- remoção destrutiva dos dados da instância;
- adapters de lifecycle além do systemd.
