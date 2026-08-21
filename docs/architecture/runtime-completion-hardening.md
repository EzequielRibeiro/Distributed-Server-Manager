# B12 — Runtime Completion & Hardening

## Objetivo

B12 fecha o bloco B6–B12 tornando o runtime de instâncias serializado, crash-consistent, limitado, observável e validável em múltiplas instâncias/jogos sem introduzir lógica específica de jogo nas camadas genéricas.

## Estado final

Cada instância expõe um contrato de saúde derivado de `desired_state`, `observed_state`, `reconcile_status` e da operação mutável local em curso.

```text
Controller desired state
        ↓
Agent local record
        ↓
operation lock + journal
        ↓
provision / lifecycle / reconcile
        ↓
observed state
        ↓
health projection + metrics + heartbeat
```

Estados de saúde finais: `healthy`, `transitioning`, `degraded` e `unknown`.

## Concorrência

Toda mutação relevante usa um lock por `instance_id`. Provisioning, lifecycle e reconciliation da mesma instância não podem executar simultaneamente. Instâncias distintas mantêm locks independentes e continuam paralelizáveis.

O lock é local ao Agent, baseado em `flock`, possui timeout limitado e não aceita nomes de arquivos vindos do Controller sem validação de token.

## Crash consistency

Cada mutação passa por `runtime_operation`, que grava atomicamente um journal em:

```text
CAPIVARA_AGENT_STATE_DIR/instance-operations/<instance-id>.json
```

O journal transita por `running → completed|failed`. Na inicialização do Agent, registros deixados em `running` por encerramento abrupto são convertidos para `interrupted`. O reconciler então converge novamente o runtime a partir da RuntimeSpec local persistida.

## Limites operacionais

`runtime_limits.py` centraliza limites bounded para:

- timeout de aquisição de lock;
- timeout total de provisioning;
- timeout de start/stop;
- timeout de reconciliation;
- máximo de retries de reconciliation;
- limites de filas de comandos/provisioning.

Valores configuráveis sempre passam por limites mínimos/máximos locais; o Controller não pode transformar um limite em execução ilimitada.

## Observabilidade

O Agent mantém métricas duráveis de runtime em:

```text
CAPIVARA_AGENT_STATE_DIR/metrics/instance-runtime.json
```

Incluem contadores de provisioning, lifecycle, reconciliation, drift, recovery e falhas, além de durações agregadas e profundidade observada das filas locais. O heartbeat projeta `instance_runtime_health` e `instance_runtime_metrics` sem criar um sistema paralelo à Universal Event Platform.

O Controller persiste a projeção final por instância em `agent_instance_runtime_health` (migration 031, com paridade SQLite/MySQL/PostgreSQL).

## Segurança e isolamento

B12 preserva as fronteiras das fases anteriores:

- nenhum shell, argv opaco ou unit name é aceito do Controller;
- RuntimeSpec continua validada e vinculada ao Agent proprietário;
- materialização privilegiada continua restrita ao helper root dedicado da B10;
- ownership inconsistente nunca é autorreparado;
- paths locais derivados de `instance_id` passam por validação;
- arquivos de lock, journal, health e métricas usam diretórios do state root e permissões restritas;
- duas instâncias possuem lock e journal independentes;
- particularidades de jogos continuam exclusivamente nos Game Runtime Profiles.

## Gate final

O bloco de runtime é considerado completo quando CI prova:

```text
create/provision
  → content + reserved ports
  → GameRuntimeProfile
  → RuntimeSpec
  → materialize
  → start/status
  → lifecycle concorrente bloqueado
  → process/runtime drift
  → recovery
  → Agent restart/interrupted journal recovery
  → health projection
  → stop/restart/remove
```

B12 não cria release e não modifica instalações ativas. A integração operacional continua passando pelo fluxo normal de release/update do Capivara.
