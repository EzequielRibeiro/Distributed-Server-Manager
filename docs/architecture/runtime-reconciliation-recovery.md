# B11 — Runtime Reconciliation & Recovery

## Objetivo

B11 transforma o runtime do Agent de um executor de comandos em um controlador local de estado desejado. Depois que B10 provisiona e materializa uma instância, o Agent mantém continuamente `desired_state` e `observed_state` convergentes mesmo quando o Controller está temporariamente indisponível.

```text
RuntimeSpec persistida no Agent
          │
          ▼
 Continuous Reconciler
          │
    ┌─────┼───────────┐
    ▼     ▼           ▼
 inspect  drift     adapter status
    │     detection    │
    └─────┬────────────┘
          ▼
   recovery policy
          │
          ▼
 running / stopped / degraded
```

## B11.1 — Reconciliation Contract

Cada instância materializada preserva localmente:

- `desired_state`;
- `observed_state`;
- `reconcile_status`;
- `reconcile_retry_count`;
- `reconcile_last_attempt_at`;
- `reconcile_last_success_at`;
- `reconcile_next_retry_at`;
- `reconcile_last_error`;
- `reconcile_drift`;
- `reconcile_last_action`.

Estados saudáveis são idempotentes: quando `desired_state` e `observed_state` já convergem, nenhuma ação de lifecycle é necessária.

## B11.2 — Continuous Reconciler

`runtime_reconciler.py` percorre as identidades locais do Agent em intervalo próprio. O loop não depende do sucesso do heartbeat; uma falha de rede com o Controller não interrompe a manutenção das instâncias.

Parâmetros locais padrão:

```text
reconcile_interval_seconds = 15
reconcile_failure_threshold = 3
reconcile_base_backoff_seconds = 15
reconcile_max_backoff_seconds = 300
```

## B11.3 — Recovery após restart/reboot

As RuntimeSpecs materializadas permanecem em `CAPIVARA_AGENT_STATE_DIR/instances`. Quando o processo do Agent volta, o reconciler lê essas identidades novamente, inspeciona o runtime e reaplica a política de convergência. Nenhum estado volátil do Controller é necessário para reconstruir o ciclo local.

## B11.4 — Drift Detection

Drifts reconhecidos inicialmente:

- `runtime_missing`: unit materializada deixou de existir;
- `runtime_modified`: unit Capivara existe, mas difere da RuntimeSpec persistida;
- `process_not_running`: estado desejado é `running`, mas o processo não está ativo;
- `unexpected_running`: estado desejado é `stopped`, mas o processo está ativo;
- `ownership_violation`: unit existe sem ownership Capivara válido.

Runtime ausente ou modificado, quando a identidade local continua válida, pode ser rematerializado pelo helper root restrito criado na B10.

`ownership_violation` nunca é reparado automaticamente. O reconciler entra em retry/degraded e exige intervenção administrativa em vez de sobrescrever uma unit que não consegue provar ser do Capivara.

## B11.5 — Automatic Recovery Policy

```text
desired=running + observed!=running  -> start
desired=stopped + observed=running  -> stop
runtime missing/modified + ownership local válido -> rematerialize
ownership inválido -> refuse repair + degraded
```

Após qualquer reparo, o runtime passa novamente pela reconciliação B8 e precisa provar convergência final.

## B11.6 — Retry e backoff

Falhas incrementam contador persistente. O intervalo usa backoff exponencial limitado:

```text
base * 2^(retry_count - 1)
```

até `reconcile_max_backoff_seconds`. Ao atingir `reconcile_failure_threshold`, o estado passa a `degraded`. Uma reconciliação bem-sucedida zera contador, erro, drift e próxima tentativa.

Isso evita restart loops agressivos e mantém o Agent responsivo.

## B11.7 — Controller Synchronization & Events

O heartbeat envia `instance_reconciliation` como projeção estruturada. O Controller persiste a última visão em `agent_instance_reconciliation`, com migrations equivalentes para SQLite, MySQL e PostgreSQL.

Eventos locais produzidos:

- `INSTANCE_DRIFT_DETECTED`;
- `INSTANCE_RECONCILE_STARTED`;
- `INSTANCE_RECONCILE_COMPLETED`;
- `INSTANCE_RECOVERED`;
- `INSTANCE_RECONCILE_FAILED`;
- `INSTANCE_DEGRADED`.

Esses eventos seguem o mesmo producer durável de runtime e podem ser ingeridos pela Universal Event Platform.

## B11.8 — Segurança e hardening

- nenhum shell, argv ou unit name é recebido do Controller;
- o reconciler opera somente instâncias locais cujo `agent_id` coincide com a identidade do Agent;
- units são derivadas do `instance_id` e ownership é validado antes de reparo;
- rematerialização continua passando pelo helper root B10, não pelo daemon principal;
- ownership inconsistente nunca é sobrescrito automaticamente;
- retries têm threshold e backoff persistentes;
- falhas de reconciliação não derrubam heartbeat nem o loop principal;
- package e updater transportam o reconciler de forma validada e rollback-safe.

## Critério de conclusão

B11 está concluída quando uma instância já provisionada consegue:

```text
processo morre
    ↓
Agent detecta drift
    ↓
recovery permitido
    ↓
runtime converge novamente
```

bem como sobreviver a restart do Agent/reboot conceitual por reconstrução do estado local, recusar reparos quando ownership não pode ser provado, aplicar backoff em falhas repetidas e projetar o estado resultante de volta ao Controller.

A reconciliação contínua não substitui B12. A próxima fase trata completion/hardening global, concorrência, limites operacionais, observabilidade final e validação end-to-end do bloco de runtime.
