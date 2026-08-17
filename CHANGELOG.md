# DSM CHANGELOG

## v1.1.0 — 2026-08-17

- Adiciona instalação real em raiz temporária no gate Linux
- Valida reinstalação, bootstrap, readiness e health HTTP do Dashboard
- Renderiza unidades systemd com `DSM_ROOT` configurável e executa `systemd-analyze verify`

- Adiciona bootstrap idempotente do primeiro administrador, controller e agent
- Adiciona diagnóstico estruturado `dsm operations readiness`
- Valida o ciclo de provisionamento, auditoria, backup e recuperação
- Implementa backup e restauração para SQLite, PostgreSQL, MySQL e MariaDB
- Exige confirmação explícita para restauração destrutiva do banco
- Integra backup externo e restauração ao rollback do atualizador
- Inclui todas as migrations multi-database no pacote reproduzível de release
- Homologa instalação e reinstalação em Linux com health check via systemd

- Corrige o caminho do serviço agregado de workers do Dashboard
- Inicializa estados com o padrão `*_state.json` usado pela API
- Inclui o estado consolidado `dashboard_state.json` no agregador
- Migra unidades individuais antigas sem duplicar processos workers

## v1.1.0-dev.1 — 2026-08-09

- Persistência SQLite com migrações versionadas
- Comandos `dsm database init|migrate|status|check|backup`
- Inicialização automática do banco pelo instalador
- Migrações integradas ao rollback transacional do updater
- Compatibilidade preservada com os estados JSON existentes

## v1.0.0 — 2026-08-09

### Recursos incorporados nesta entrega

- Catalog v2 com contratos de runtime, conteúdo e compatibilidade
- Integração do Catalog v2 com CLI, API e Dashboard
- Planejamento transacional de mods, plugins e modpacks
- Instalador local/remoto com conta de serviço configurável
- Atualizador com backup atômico, progresso e preservação de serviços
- Fonte única de versão para instalador, updater, Console e Dashboard
- Pacotes de release reproduzíveis com manifesto e SHA-256
- CI para Bash, JSON, Python, JavaScript, instalador, updater e Catalog v2
- Publicação automática de GitHub Release por tag SemVer

### Segurança operacional

- Atualizações da mesma versão são bloqueadas por padrão
- Downgrades exigem a opção explícita `--allow-downgrade`
- Dados locais, logs, caches, instâncias e SteamCMD não entram na release

Primeira versão profissional, com arquitetura modular completa (10
módulos). Reescrita total em relação à versão anterior (script único
com módulos soltos).

### Base funcional

- Core: log estruturado, config validada, trava anti-concorrência,
  bootstrap único
- Server: start/stop/restart/status com validação de pré-voo
- Mods: checagem via API pública da Steam, detecção de mods manuais
  (via `meta.cpp`), rollback de versão, sincronização de keys
- Monitor: watchdog com backoff, saúde geral, alertas sem repetição,
  log de eventos estruturado
- Doctor: diagnóstico com pontuação 0-100, relatório em texto e JSON
- Backup: completo (checksum + manifesto) e snapshot incremental
  rápido, com retenção configurável
- Scheduler: agendador próprio (systemd, sem depender de cron),
  tarefas em arquivos `.task`, histórico de execução
- Notification: Discord + Telegram, com fila de reenvio automático
- Dashboard: interface web com API própria, autenticação e dois
  papéis de acesso (admin/operador)
- Install/Release: instalador com wizard completo, serviços systemd,
  atualização preservando configuração e dados
- Reinício automático nativo do DayZ com avisos aos jogadores em
  30/20/15/5 minutos (via `messages.xml`)
