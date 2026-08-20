# Fase 18 — Atualização remota de Agents

## Objetivo

Atualizar Agents remotamente sem transformar o heartbeat em um mecanismo privilegiado de escrita e sem atualizar toda a infraestrutura simultaneamente.

## Estado persistido

`agent_update_state` registra:

- `installed_version` — versão confirmada pelo heartbeat;
- `available_version` — versão oferecida pelo rollout;
- `update_channel` — `stable`, `beta` ou `local/manual`;
- `desired_version` — alvo do rollout atual;
- `update_status` — `idle`, `planned`, `updating`, `verifying`, `completed` ou `failed`;
- `rollout_id`, `batch_number`, `batch_position`;
- `requested_at`, `last_update`, `last_error`.

A versão instalada é sempre reportada pelo próprio Agent. `last_update` somente é gravado depois que o Agent volta `online` reportando exatamente a versão desejada.

## Rollout seguro

Um rollout ordena Agents em lotes:

```text
batch 1
  Agent A
  Agent B
     ↓
update
     ↓
heartbeat online + versão esperada
     ↓
batch 2
```

Todos os membros dos lotes anteriores precisam estar `completed`. Um `failed` bloqueia a progressão automática e exige ação administrativa.

`batch_size=1` implementa atualização serial. Em infraestrutura maior, o administrador pode aumentar o tamanho do lote.

## Linux: separação de privilégios

O processo `capivara-agent` continua sem privilégios e não recebe permissão para escrever em `/opt/capivara-agent`.

Fluxo:

```text
heartbeat autenticado
  ↓
update command
  ↓
/var/lib/capivara-agent/update-request.json
  ↓
systemd.path
  ↓
capivara-agent-update.service (root)
  ↓
GitHub Release imutável
  ↓
SHA-256 externo
  ↓
manifest + hashes internos
  ↓
extração segura
  ↓
substituição dos arquivos do Agent
  ↓
restart
  ↓
heartbeat online com nova versão
```

O helper root rejeita membros de archive que não sejam arquivos/diretórios normais ou que tentem escapar do diretório temporário.

## Canais

- `stable`: release estável oficial.
- `beta`: prerelease futura/experimental.
- `local/manual`: estado administrável para ambientes isolados; o updater remoto não tenta baixar conteúdo externo nesse canal.

O canal `local/manual` deliberadamente não converte um Controller remoto em servidor de arquivos privilegiado. A atualização é fornecida pelo administrador usando o pacote local canônico.

## Invariantes

1. Heartbeat não escreve diretamente em `/opt/capivara-agent`.
2. O próximo lote não é liberado antes da validação do anterior.
3. Versão instalada vem do Agent, não de suposição do Controller.
4. Um Agent já na versão desejada pode concluir o rollout sem reinstalação.
5. Falha bloqueia lotes posteriores.
6. Releases são verificadas por SHA-256 e manifest interno.
7. O fluxo não modifica a instalação ativa do Controller em `/opt/dsm`.
