# Capivara DSM 2.0.132 — Candidata após PR #981

**Estado: preparação para release, ainda não publicada.** A alteração desta candidata não ativa `release/RELEASE_TRIGGER`, não cria tag, não instala o DSM e não reinicia serviços.

## Entregas consolidadas

- **#981 — Minecraft Server Pack / NeoForge**: recuperação segura após commit, checkpoints duráveis, confirmação e arquivamento idempotentes, preservação do mundo e rollback; worker independente do heartbeat; proteção contra publicação de conclusão prematura no Controller.
- **#981 — Homologação funcional**: NeoForge 26.1.2.109 real com systemd, helper privilegiado, backup atestado e worker de recuperação em instância descartável; simulações de SIGKILL nas etapas de arquivamento.
- **#981 — Compatibilidade**: validações nativas Windows para transação e persistência de diários, protocolo HTTP Controller–Agent e proteção da revisão do bundle contra mensagens antigas.
- **#986 e #985 — DayZ**: proteção de rollback/backup de manutenção e serialização de atualizações de game-data pendentes.
- **#980 — DayZ**: configuração por instância do caminho privado do BattlEye.
- **#982 — Steam**: fallback autenticado e detecção de timeout.
- **#983 — DayZ**: permissões de DLC com base nos depots Steam verificados.

## Validações já registradas

- PR #981 incorporada à `main` no commit `8f58668e62c343dadcca4a0fd6241d58372fd71e`.
- Os 40 workflows do último HEAD da PR #981 foram aprovados, incluindo Windows, MariaDB, MySQL e integração externa.
- Build preliminar da `main` e verificação de SHA-256 aprovados. O pacote definitivo da candidata deverá ser produzido a partir do **commit final de publicação**.
- Validada recuperação após reinício de processo; **não** houve reboot físico controlado do host.

## Gates antes da publicação

1. Aprovar a CI do commit de versão 2.0.132 e a prontidão de release, inclusive comparação de schemas SQLite/PostgreSQL/MySQL/MariaDB.
2. Executar build reproduzível dos pacotes DSM, Linux Agent e Windows Agent; validar SHA-256, manifesto e identidades dos commits.
3. Concluir auditoria de atualização e rollback sobre a candidata instalada `2.0.132-rc.4`; preservar backups e instâncias. Não interpretar `main` 2.0.131 como instalação do host.
4. Validar operacionalmente recuperação após reboot de laboratório isolado ou registrar aceitação explícita do risco residual. Confirmar telemetria e heartbeat.
5. **Somente em mudança separada e autorizada**, atualizar `release/RELEASE_TRIGGER` para `2.0.132` com marcador de publicação, criar tag imutável, publicar artefatos e executar smoke test público.

Não há autorização automática de implantação no `horizon-server` nem de reinício do Minecraft 005.
