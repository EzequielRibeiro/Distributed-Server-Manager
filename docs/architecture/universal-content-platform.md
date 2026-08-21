# C4 — Universal Content Platform

## Objetivo

C4 transforma conteúdo instalável em desired state do Control Plane. O Controller não executa shell remoto nem conhece regras específicas de jogos; ele persiste uma atribuição declarativa e o Agent reconcilia a instalação localmente.

## Contrato

`CapivaraContentAssignment` identifica `agent_id`, `instance_id`, `content_id`, jogo, tipo, versão, provider, target, artifact, dependências, conflitos, desired state e checksum. `installed` solicita presença; `absent` solicita remoção apenas do target gerenciado.

Targets padrão são isolados por conteúdo (`mods/<content-id>`, `plugins/<content-id>`, etc.) para que uma remoção não apague conteúdo vizinho.

## Fluxo

```text
Catalog / Admin
      |
      v
Controller content_assignments
      |
      | heartbeat response
      v
Agent content_client
      |
      +-- validate ownership
      +-- resolve confined target
      +-- download/copy
      +-- verify checksum
      +-- safe extract
      +-- atomic replace
      |
      v
instance/content/<target>
      |
      | next heartbeat: content_state ACK
      v
Controller agent_content_state
```

O Controller retransmite uma revisão até receber `applied_revision + applied_checksum` com `status=applied`. O modelo é portanto at-least-once e idempotente.

## Segurança

- comandos, scripts e shell em artifacts são rejeitados pelo contrato;
- targets absolutos, `..` e escapes do diretório da instância são rejeitados;
- downloads remotos do reconciler C4 exigem HTTPS;
- SHA-256 é validado quando declarado;
- ZIP/TAR são inspecionados contra traversal; links TAR são recusados;
- artifacts `local` só podem vir de `CAPIVARA_GAME_DATA_ROOT`;
- o Agent valida ownership da instância antes de instalar ou remover;
- instalação usa staging e troca atômica; remoção só alcança o target gerenciado.

Providers que demandam resolução especializada (`steam`, `custom`, `source-build`) permanecem declarados no contrato, mas falham fechados no reconciler independente até serem resolvidos para um artifact confiável por uma capacidade/provider do Agent. Isso evita transformar C4 em execução remota arbitrária. HTTP, HTTP Archive, GitHub resolvido e artifacts locais são executáveis no reconciler Linux desta fase.

## Persistência

Migration 035 cria, com paridade SQLite/PostgreSQL/MySQL-MariaDB:

- `content_assignments`: desired state atual;
- `content_assignment_revisions`: histórico imutável;
- `agent_content_state`: projeção aplicada/reportada pelo Agent.

A identidade de uma atribuição é `(instance_id, content_id)` e alterações incrementam `revision`. Conteúdo idêntico é no-op idempotente.

## Eventos e observabilidade

Alterações administrativas publicam `CONTENT_ASSIGNMENT_UPDATED` na Universal Event Platform C1. C4 não produz um Universal Event por heartbeat ou por byte transferido. Métricas detalhadas de transferência/provider podem ser adicionadas à C3 sem acoplar o content store ao sistema de métricas.

## Interfaces

Controller CLI:

```text
cap content-store list
cap content-store set ...
cap content-store history <assignment-id>
```

A `cap content` existente continua reservada à compatibilidade/runtime local do Agent.

HTTP administrativo:

```text
GET  /api/content
POST /api/content
```

A rota é composta em `dashboard/server_part13.py`; `dashboard/server.py` não cresce.

## Compatibilidade

`installer/content_manager.sh`, `content_planner.sh`, os providers existentes e `content_installations` continuam disponíveis para fluxos legados. C4 cria o novo plano distribuído e não migra automaticamente registros legados sem uma política explícita de ownership/versionamento.

## Fora do escopo desta fase

- avaliação de alert thresholds (fases de automação);
- WebSocket/SSE (D2);
- execução de shell declarada pelo Controller;
- marketplace/assinatura de extensões;
- apagar dados não gerenciados da instância.
