# C1 — Universal Event Platform

## Objetivo

C1 cria um contrato único para eventos produzidos pelo Controller, Agents e runtimes. A plataforma substitui integrações ad-hoc por um envelope normalizado, persistência multi-backend, entrega idempotente do Agent e superfícies comuns de consulta.

```text
Producer
   │
   ▼
CapivaraUniversalEvent
   │
   ▼
Universal Event Store
   │
   ├── CLI / API / Timeline
   ├── Alerts (consumer)
   ├── Audit (consumer)
   ├── Automation (consumer futuro)
   └── Stream (consumer futuro)
```

C1 não implementa o Automation Engine nem WebSocket streaming. Ele fornece a fonte de verdade que essas camadas consumirão.

## Envelope canônico

`core/event_platform.py` define `schema_version=1` e o kind `CapivaraUniversalEvent`.

Campos principais:

- `event_id`: identidade idempotente;
- `event_type`: `UPPER_SNAKE_CASE`;
- `occurred_at`: timestamp do produtor;
- `source` e `source_id`;
- `severity`: `debug|info|warning|error|critical`;
- `agent_id` e `instance_id`, quando aplicáveis;
- `correlation_id` e `causation_id` para encadear operações;
- `actor_type` e `actor_id` para autoria;
- `data`: payload estruturado específico do evento.

Particularidades de jogos nunca entram no contrato base. Elas permanecem em `data` e nos Game Runtime Profiles.

## Persistência

Migration `032_universal_events.sql` existe com paridade para:

- SQLite;
- PostgreSQL;
- MySQL/MariaDB.

A tabela `universal_events` é append-oriented. Atualizações destrutivas de eventos não fazem parte do contrato C1. Índices cobrem tipo, Agent, instância, severidade, correlação e tempo.

A tabela histórica `events` criada na fundação do banco é considerada legado. Novos produtores devem publicar pela `UniversalEventRepository`; ela é a fonte canônica para as fases seguintes.

## Agent → Controller

Eventos locais do runtime continuam sendo gravados de forma durável no Agent em:

```text
CAPIVARA_AGENT_STATE_DIR/events/instance-runtime.jsonl
```

O fluxo C1 é at-least-once:

```text
runtime emits event
      ↓
local JSONL durable queue
      ↓
heartbeat.runtime_events
      ↓
authenticated Controller ingestion
      ↓
universal_events
      ↓
accepted_event_ids
      ↓
Agent removes only ACKed records
```

`event_id` torna retransmissões idempotentes. Se a comunicação cair depois da persistência e antes do ACK, o Agent retransmite; o Controller reconhece o mesmo ID sem duplicá-lo.

Registros B11 antigos sem `event_id` recebem UUIDv5 determinístico durante leitura/tradução, permitindo deduplicação e drenagem da fila sem descartar o histórico local.

## Segurança

A ingestão pelo heartbeat preserva a identidade autenticada do Agent:

- `agent_id` do evento deve coincidir com o Agent autenticado;
- quando houver `instance_id`, a instância precisa pertencer àquele Agent;
- eventos inválidos ou spoofed não recebem ACK;
- o Controller nunca confia em identidade arbitrária dentro do payload;
- payload de evento não é interpretado como shell/argv.

A API administrativa `/api/events` exige role `admin` ou `controller`. A exposição tenant-aware para clientes deverá ser feita por projeções/scopes explícitos, nunca liberando o event store global diretamente.

## Superfícies públicas

### CLI

```text
cap events list [--type TYPE] [--agent ID] [--instance ID] [--severity LEVEL] [--limit N] [--json]
cap events show <event-id> [--json]
cap events publish <TYPE> --source SOURCE [--severity LEVEL] [--data-json JSON] [--json]
```

### HTTP

```text
GET  /api/events
GET  /api/events?event_id=<id>
POST /api/events
```

Filtros GET: `type`, `agent_id`, `instance_id`, `severity`, `correlation_id`, `limit`.

## Eventos iniciais

O runtime distribuído B11/B12 já produz eventos que passam a ter destino canônico no C1, incluindo:

- `INSTANCE_DRIFT_DETECTED`;
- `INSTANCE_RECOVERED`.

Novos produtores devem adotar a mesma plataforma para famílias como:

- `AGENT_*`;
- `PLACEMENT_*`;
- `INSTANCE_*`;
- `INSTALL_*` / `PROVISION_*`;
- `BACKUP_*`;
- `INFRASTRUCTURE_*`;
- `CONTENT_*`;
- `BROADCAST_*` quando D1 existir.

## Observabilidade e evolução

O event store não substitui métricas B12 nem o Alert Engine. Eventos descrevem fatos discretos; métricas descrevem séries/estado agregado; alerts representam condições que exigem atenção.

Consumidores futuros devem manter esse desacoplamento:

```text
Universal Event Store
     ├── Timeline projection
     ├── Alert rules/projection
     ├── Audit projection
     ├── Automation subscriptions
     └── WebSocket stream
```

C1 conclui a fundação quando CI prova contrato, persistência, idempotência, isolamento de identidade/ownership, fila local durável com ACK, API/CLI e paridade de migrations.
