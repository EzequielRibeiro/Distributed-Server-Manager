# D2 — Real-Time & API Platform

D2 transforma as plataformas universais do Capivara em uma superfície externa estável, versionada e segura para integrações, dashboards e automação de terceiros.

## Arquitetura

```text
C1 Events ───────────────┐
C3 Observability ────────┤
Instance inventory ──────┤
D1 Automation/Broadcast ─┤
                         ▼
                 D2 API Read Model
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
          REST /api/v1/*       SSE event stream
              │                     │
              └──────────┬──────────┘
                         ▼
                 Scoped API Tokens
```

## Contrato externo v1

Leitura:

- `GET /api/v1/status`
- `GET /api/v1/events`
- `GET /api/v1/observability/latest`
- `GET /api/v1/instances`
- `GET /api/v1/stream/events`

Escrita intencional:

- `POST /api/v1/broadcasts`
- `POST /api/v1/automation/fire`

A versão está no path. Mudanças incompatíveis exigem uma nova versão de API.

## Real-time

O transporte em tempo real inicial é Server-Sent Events (SSE). Ele é adequado ao fluxo predominante Controller → consumidor, funciona sobre HTTP padrão, atravessa proxies com menos complexidade que WebSocket e não introduz dependências externas no Controller.

Cada evento SSE carrega um `id` opaco. Esse ID é também um cursor estável. O consumidor pode reconectar com `Last-Event-ID` ou `?cursor=` e continuar depois do último evento recebido. O cursor codifica apenas a posição `(occurred_at,event_id)`, sem segredos.

O stream é deliberadamente limitado por conexão e envia keepalive. O cliente deve reconectar. Isso evita sessões eternas e mantém comportamento previsível durante deploys e failover.

## Autenticação

Tokens D2 possuem formato `capv2_<prefix>_<secret>`. Apenas SHA-256 do segredo é persistido. O valor completo é exibido somente na criação.

Scopes oficiais:

- `events:read`
- `observability:read`
- `instances:read`
- `realtime:read`
- `broadcasts:write`
- `automation:write`
- `api:admin`

`api:admin` satisfaz qualquer scope. Tokens podem expirar e podem ser revogados. Credenciais revogadas ou expiradas falham fechadas.

## Administração

Dashboard/API administrativa:

- `GET /api/api-tokens`
- `POST /api/api-tokens` com `operation=create|revoke`

CLI:

```text
cap api token-create <nome> --scope events:read --scope realtime:read
cap api token-list
cap api token-revoke <token-id>
cap api status
```

## Auditoria

Requisições externas são registradas em `api_request_log` com token, método, path, status, latência e endereço remoto. O segredo do token e o header Authorization nunca entram no log.

## Segurança

A API externa não aceita shell, comando arbitrário, paths de arquivo ou credenciais RCON. Escritas reutilizam os contratos estruturados D1. O stream é somente leitura. A administração dos tokens continua protegida pela autenticação administrativa normal do Controller.

## Banco de dados

A migration 038 é mantida em paridade para SQLite, PostgreSQL e MySQL/MariaDB.

## Evolução

D2 estabelece a fronteira pública. WebSocket pode ser adicionado futuramente somente quando existir um caso bidirecional real; não substitui SSE para o feed de eventos. Novos recursos incompatíveis devem nascer em `/api/v2` em vez de quebrar `/api/v1`.
