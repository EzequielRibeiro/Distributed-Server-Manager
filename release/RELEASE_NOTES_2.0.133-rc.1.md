# Capivara DSM 2.0.133-rc.1 — Candidata de homologação (18/11/2026)

**Canal:** pré-lançamento (prerelease), não versão estável. A última versão estável permanece **v2.0.132**. Publicar estes artefatos não autoriza instalá-los nos servidores existentes, alterar serviços ou reiniciar jogos.

## Alterações incorporadas desde v2.0.132

- **Backups e cota contratual (#1066; PRs #1072 e #1079):** contabilização dos arquivos históricos físicos e envio do limite de armazenamento resolvido pelo Controller para o Agent. Aceite operacional após implantação ainda pendente.
- **DayZ (#977; PR #1069):** auditoria de descoberta de DLC e avaliação somente leitura de ownership/permissões. Não efetua reparos automáticos; aceite operacional ainda pendente.
- **SteamCMD (#970; PR #1076):** tratamento de sufixo Steam Account ID na interpretação de confirmação de login. Reutilização real da sessão com download Workshop autenticado ainda não foi comprovada.
- **Atualização e continuidade de jogos (#928; PRs #1042, #1077, #1078):** diagnóstico de incompatibilidades, guardas systemd e journaling de identidade de processos/unidades em testes isolados. **Não foi habilitada a atualização sem drenagem**; o atualizador existente ainda pode parar Minecraft e DayZ.
- **Minecraft Server Pack / ATM11 (#1013):** alterações de segurança e recuperação transacional incorporadas desde a release anterior, mas a migração 0.13→0.14 do mundo privado não foi homologada integralmente.

## Limites conhecidos e critérios de promoção estável

1. A issue **#1013** mantém o bloqueio de release estável até a correção/aceite da migração Minecraft 0.14. Esta candidata não o elimina.
2. A issue **#928** ainda não autoriza `update.sh --no-drain`; não executar `cap update run` supondo continuidade de PIDs/jogos.
3. Antes de implantar: validar backup íntegro, baseline/migrações de banco, rollback, heartbeat Controller/Agent, preservação de instâncias e versão do bootstrap do atualizador no host alvo.
4. **Não executar deploy automático** no Horizon, node1 ou VPS externa. Instalação requer autorização operacional independente.
5. Validar SHA-256 e manifestos dos pacotes DSM e Agents, identidade do commit/tag e o smoke test público desta prerelease.

Este documento descreve uma candidata de homologação, não certifica que os testes E2E com jogos reais, a migração do banco real, o updater sem drenagem ou a migração privada ATM11 tenham sido concluídos.
