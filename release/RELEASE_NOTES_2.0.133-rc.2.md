# Capivara DSM 2.0.133-rc.2 — Candidata de correção de backup (18/11/2026)

**Canal:** pré-release. A v2.0.132 permanece a última versão estável. Esta publicação **não autoriza instalação ou reinicialização** dos jogos.

## Correção incluída desde 2.0.133-rc.1

- **PR #1081 / issue #1066:** o Controller agora encaminha ao Agent comandos de exclusão de backups solicitados expressamente pela área do cliente (`reason=customer`) ou manualmente pelo administrador (`reason=manual`), sem precisar ativar a exclusão automática. O identificador original de cada solicitação pendente é preservado.
- A retenção e a limpeza automáticas continuam bloqueadas por padrão; motivos `age_retention`, `operational_retention` ou ausentes não são transformados em autorização manual.
- Testes da correção e CI de PR #1081: 18/18 workflows aprovados, incluindo `Universal Smart Backup`.

## Bloqueio de implantação / auditoria obrigatória

**NÃO INSTALAR ESTA CANDIDATA NO HORIZON AINDA.** O Horizon (2.0.133-rc.1) registra solicitações `delete / pending` antigas de DayZ 001. Ao instalar a rc.2, o Worker Hybrid poderá executá-las automaticamente no próximo ciclo, **sem novo clique nem confirmação**.

Antes de qualquer implantação, um operador deve verificar em modo somente leitura a lista completa de `backup_jobs` pendentes por `command_id`, `backup_id`, `instance_id`, `reason`, `requested_by` e `created_at`, conciliando cada artefato físico, e comprovar que o último backup operacional restaurável não está na lista a excluir. A proteção do último backup feita por `_protect_age_retention_delete` só é executada no registro do pedido quando a política opt-in de retenção por idade está ativa; **não é uma verificação universal no momento do despacho**. Sem essa auditoria, a implantação permanece bloqueada. Não habilitar `DSM_BACKUP_ALLOW_AUTOMATIC_DELETION=1` e não excluir manualmente arquivos ou linhas do banco.

## Restrições herdadas da rc.1

- **#928**: atualização sem drenagem ainda não autorizada; o atualizador existente pode parar/reiniciar jogos ativos.
- **#1013**: migração Minecraft ATM11 0.14 com mundo privado ainda não homologada; promoção estável bloqueada.
- **#970**: reutilização SteamCMD + download Workshop autenticado ainda não atestados em teste isolado.
- Integridade dos pacotes de release precisa passar no smoke test público, com SHA-256 e manifestos.
- Publicação GitHub não substitui validação nem instalação em hosts.

Esta candidata contém somente a correção de entrega da fila e não demonstra exclusão física, inventário de backups em produção ou recuperação de arquivos.
