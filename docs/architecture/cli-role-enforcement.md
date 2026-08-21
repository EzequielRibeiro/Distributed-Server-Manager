# CLI role enforcement

## Objetivo

`cap` resolve o papel local antes de encaminhar comandos sensíveis. A resolução é observacional: não inicializa repositories, não executa migrations, não atualiza health e não reconcilia placement.

Roles oficiais:

- `controller`
- `agent`
- `hybrid`
- `unknown` apenas como estado seguro de falha de resolução

## Resolução local

`core/role_context.py` usa, nesta ordem:

1. `CAPIVARA_NODE_ROLE` / `DSM_NODE_ROLE` no ambiente;
2. `DSM_NODE_ROLE` em `config/dsm.conf`;
3. `DSM_NODE_ROLE` em `config/agent.conf` — já persistido pelo instalador e atualizado na promoção Controller -> Hybrid;
4. configuração JSON do Agent Linux standalone;
5. fallback SQLite legado aberto com `mode=ro` e sem qualquer inicialização/migration;
6. `unknown`, com bloqueio do dispatch.

Arquivos shell são lidos como assignments simples; eles nunca são `source` pelo resolver.

## Matriz de comandos

### Controller / Hybrid

- `cap infrastructure ...`
- `cap agent deploy ...`
- `cap agent ports show|check <agent-id>`
- `cap agent ports set <agent-id> ...`
- `cap user ...`
- `cap catalog ...`
- `cap database|db ...`
- `cap instance ...`
- `cap operations|ops ...`

### Agent / Hybrid

- `cap agent status|info|health|heartbeat`
- `cap agent capabilities|network`
- `cap agent ports show|check` sem `agent-id`
- `cap agent game-data ...`
- `cap agent jobs ...`
- `cap agent logs|doctor`
- superfícies operacionais locais: server, monitor, mods, backup, runtime, steam, game, content e compatibility
- aliases locais start/stop/restart/status

### Todas as roles conhecidas

- `cap config ...`
- `cap update ...`

`unknown` não recebe dispatch operacional. O comportamento é fail-closed.

## Colisão de `agent ports`

A assinatura define a autoridade:

```text
cap agent ports show
cap agent ports check
    -> Agent/Hybrid, inspeção local

cap agent ports show <agent-id>
cap agent ports check <agent-id>
cap agent ports set <agent-id> ...
    -> Controller/Hybrid, estado autoritativo
```

Assim o nome da superfície permanece estável sem misturar contexto local e administrativo.

## Help

`cap help` exibe somente a superfície da role resolvida. `cap help --all` mostra a referência completa. Isso é ergonomia; o bloqueio efetivo continua no dispatch.

## Segurança

O enforcement acontece antes de carregar CLIs administrativas. Uma role incompatível não chega a abrir backend, iniciar migration ou executar comando legado. O fallback SQLite existe apenas para instalações antigas e usa URI `mode=ro`.
