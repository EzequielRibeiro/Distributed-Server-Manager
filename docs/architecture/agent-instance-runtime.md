# Agent-owned Instance Runtime

## Objetivo

O Controller mantém política, placement e autorização. O Agent proprietário mantém a identidade operacional local da instância e executa observações/ações por meio de contratos estruturados. O Controller nunca envia shell arbitrário.

## Evolução consolidada

```text
B6  Agent-owned Runtime Foundation
B7  Runtime Adapters
B8  Runtime Materialization
B9  Game Runtime Profiles
B10 Instance Provisioning Pipeline
B11 Runtime Reconciliation & Recovery
```

B11 adiciona um reconciler local contínuo que mantém `desired_state` e `observed_state` convergentes, detecta drift, recupera processo/runtime quando a correção é segura, recusa reparo automático quando ownership não pode ser provado e aplica retry/backoff antes de declarar estado degradado.

A documentação detalhada da B11 está em `docs/architecture/runtime-reconciliation-recovery.md`. O pipeline B10 está em `docs/architecture/instance-provisioning-pipeline.md`.

## Fronteiras permanentes

- Controller não envia shell arbitrário, argv opaco ou unit names;
- `GameRuntimeProfile` é a camada que conhece particularidades do jogo;
- materializer e adapter permanecem game-agnostic;
- runtime local pertence ao Agent selecionado;
- units são derivadas de `instance_id` e possuem marcadores de ownership;
- operações privilegiadas de materialização passam pelo helper root restrito, enquanto o daemon principal continua sem root;
- o reconciler local continua operando mesmo durante indisponibilidade temporária do Controller;
- ownership inconsistente nunca é sobrescrito automaticamente.

## Lifecycle local

```text
RuntimeSpec
    ↓
Materializer
    ↓
Runtime Adapter
    ↓
Continuous Reconciler
    ↓
desired == observed
```

O runtime suporta `status`, `doctor`, `start`, `stop` e `restart`. B11 acrescenta recuperação automática segura para drift e falhas operacionais sem ampliar a autoridade remota do Controller.

## Eventos

O produtor local registra eventos estruturados em `CAPIVARA_AGENT_STATE_DIR/events/instance-runtime.jsonl`. Entre os eventos atuais estão materialização, provisioning, drift, reconciliação, recovery e degradação. A Universal Event Platform pode ingerir esse producer sem acoplamento do reconciler ao backend central.

## Próxima evolução

B12 — Runtime Completion & Hardening fecha este bloco com hardening global, concorrência, limites operacionais, observabilidade final e validação end-to-end multi-game/multi-host.
