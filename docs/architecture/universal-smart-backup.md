# C5 — Universal Smart Backup Platform

C5 transforma backup em um plano distribuído, game-agnostic e orientado a políticas.

## Fluxo

Controller → `backup_policies` → heartbeat autenticado → Agent → artifact local → estado reportado → `backup_jobs`.

Uma política define `interval_seconds`, `retention_count`, `mode`, `consistency`, `compression`, includes e excludes. O Controller agenda automaticamente um job quando não existe job ativo e o último backup concluído ultrapassou o intervalo. Pedidos manuais usam o mesmo pipeline.

## Consistência

- `live`: copia a árvore selecionada sem interromper o runtime.
- `stopped`: se a instância estiver executando, o Agent usa o lifecycle genérico para parar, criar/restaurar e iniciar novamente.
- `quiesced`: falha fechado enquanto não existir hook específico e explícito para o runtime. C5 não simula consistência de aplicação.

## Segurança

O Agent valida ownership da instância, restringe artifacts ao `CAPIVARA_BACKUP_ROOT`, impede path traversal e links durante restore e não aceita comandos shell arbitrários. Backups são identificados por UUID e SHA-256. Restore ocorre via staging e troca atômica da árvore da instância.

## Retenção

Após uma criação concluída, o Agent mantém os artifacts mais recentes conforme `retention_count`. A política é versionada de forma imutável no Controller.

## API e CLI

`GET /api/backups` lista jobs ou políticas. `POST /api/backups` aceita `operation=policy|create|restore|delete` para administradores/controller.

CLI: `cap backup-store policy-list|policy-set|history|jobs|create|restore|delete`.

O comando legado `cap backup` permanece disponível para compatibilidade local. C5 não depende de nomes, caminhos ou arquivos específicos de qualquer jogo.

## Persistência

A migration `036_universal_smart_backup.sql` existe em SQLite, MySQL/MariaDB e PostgreSQL com `backup_policies`, `backup_policy_revisions` e `backup_jobs`.
