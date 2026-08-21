# Agent local game-data and jobs CLI

## Objetivo

A B3 estende a CLI local Linux do Agent com visibilidade observacional sobre game-data e jobs executados no próprio host, sem consultar a database do Controller e sem disparar operações.

## Comandos

```text
cap agent game-data list [--json]
cap agent game-data status <game> [--json]
cap agent jobs [--active] [--limit N] [--json]
cap agent jobs show <job-id> [--json]
```

Esses comandos apenas leem arquivos de estado locais. Instalação, update, verify e heartbeat não são executados pela CLI.

## Estado local

```text
/var/lib/capivara-agent/
├── game-data/
│   └── <game>/...
├── game-data-state/
│   └── <game>.json
└── game-data-jobs/
    ├── <job>.request.json
    ├── <job>.result.json
    ├── <job>.log
    └── history/
        └── <job>.json
```

`request.json` e `result.json` são transitórios. Quando o Controller reconhece `completed` ou `failed`, o Agent grava um resumo final sanitizado em `history/` e remove os dois arquivos transitórios. O log permanece separado.

O histórico não copia o `RuntimeSelection` completo nem credenciais. Preserva apenas metadados operacionais necessários para diagnóstico: job, ação, environment, selector, status, progresso, erro, provider, game, versão, target e caminho do log.

## Inventário de game-data

Após uma execução bem-sucedida, o executor atualiza atomicamente `game-data-state/<game>.json` com:

```json
{
  "game": "dayz",
  "installed": true,
  "provider": "steam",
  "version": "current",
  "target_path": "/var/lib/capivara-agent/game-data/dayz/serverfiles",
  "last_action": "install",
  "last_job_id": "game-data-...",
  "updated_at": "...Z"
}
```

A CLI pode validar observacionalmente se `target_path` continua existindo e não está vazio. Nenhuma reparação automática é feita.

## Doctor

`cap agent doctor` inclui somente o resumo local:

- quantidade de game-data inventariados;
- jobs ativos;
- falhas recentes.

Falhas recentes geram `WARNING/degraded`, mas ausência de jogos instalados é um estado saudável e válido.

## Distribuição

`game_data_state.py` faz parte do pacote canônico do Agent Linux, é instalado junto dos demais módulos runtime e também é atualizado pelo updater checksum-enforcing.

## Limites

Esta etapa não cria SQLite local no Agent. O volume de estado é pequeno, pertencente ao próprio host e gravado atomicamente. Uma database local deverá ser considerada quando o Agent passar a possuir filas, instâncias ou histórico operacional de volume significativamente maior.
