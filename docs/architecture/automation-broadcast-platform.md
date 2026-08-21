# D1 — Automation & Universal Broadcast Platform

D1 cria o plano declarativo de automação do Capivara sobre as plataformas universais já existentes.

## Modelo

Uma regra é representada por `CapivaraAutomationRule`:

```text
WHEN trigger
IF conditions
THEN actions
```

Triggers suportados:

- `event`: eventos normalizados da C1;
- `metric`: amostras atuais da C3;
- `schedule`: expressão cron de cinco campos em UTC;
- `manual`: execução explícita.

Ações suportadas:

- `broadcast`;
- `backup` pela C5;
- `instance` (`start`, `stop`, `restart`) pela fila universal de lifecycle;
- `content` pela C4;
- `configuration` pela C2.

A regra é versionada, possui checksum determinístico, histórico imutável e `cooldown_seconds`.

## Worker

`dashboard/workers/automation_worker.py` é o consumidor reativo do Controller. Ele mantém cursor durável em `automation_runtime_state`, consome C1 em ordem `(received_at,event_id)`, avalia métricas de `observability_latest` e dispara regras de schedule. Cada evento/sample/minuto recebe `trigger_ref` estável. Uma restrição única em `automation_runs` transforma reprocessamento em no-op antes de qualquer efeito colateral.

## Universal Broadcast

`CapivaraBroadcast` é independente do jogo. O Controller resolve o escopo para instâncias concretas e cria uma entrega durável por Agent/instância.

Escopos:

```text
instance | agent | game | customer | datacenter | region | global
```

Cada broadcast possui prioridade, TTL e opção de ACK. O transporte Controller → Agent reutiliza o heartbeat autenticado. O Agent mantém estado local durável e reporta `delivered`, `acknowledged` ou `failed`. Entregas com falha podem ser reenviadas até cinco tentativas e deixam de ser elegíveis quando o TTL expira.

## Adapter boundary

O Controller nunca envia shell, comandos RCON nem credenciais através do contrato universal. O Agent resolve a instância e chama `InstanceRuntimeAdapter.broadcast()`. O método base falha fechado; cada Game Adapter precisa implementar explicitamente seu mecanismo suportado (RCON, console estruturado, API ou plugin).

## Persistência

Migration `037_automation_broadcast.sql` possui equivalentes em SQLite, PostgreSQL e MySQL/MariaDB e cria:

- `automation_rules`;
- `automation_rule_revisions`;
- `automation_runs`;
- `automation_runtime_state`;
- `broadcasts`;
- `broadcast_deliveries`.

## API

```text
GET/POST /api/automation
GET/POST /api/broadcasts
```

Somente `admin`/`controller` acessam a superfície administrativa.

## CLI

```text
cap automation rule-list
cap automation rule-set --json-body '{...}'
cap automation history RULE
cap automation fire RULE
cap automation event EVENT_TYPE
cap automation broadcast --scope global --message '...'
cap automation broadcast-list
```

## Eventos

Alterações de regra publicam `AUTOMATION_RULE_UPDATED`; novos broadcasts publicam `BROADCAST_REQUESTED` na C1.

## Compatibilidade

O scheduler e o broadcast legado, quando existirem, não são removidos nesta fase. D1 estabelece o pipeline distribuído universal. `dashboard/server.py` não recebe novas responsabilidades; a composição permanece modular em `server_part13.py` e módulos próprios.
