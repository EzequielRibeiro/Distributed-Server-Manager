# Capivara DSM 2.0.131 — Candidata

**Estado: preparação, não publicada.** Não há autorização automática de deploy nem alteração do servidor de jogo.

## Correções consolidadas
- **#959**: impedir falso sucesso nas atualizações de game-data DayZ, validando evidências do destino real da instância.
- **#960**: segurança na restauração de backups e recuperação após falha parcial (já integrada antes de 2.0.130).
- **#961**: confirmar prontidão sustentada do DayZ após atualização, em vez de aceitar inicialização transitória.
- **#962**: configurar ACL na raiz de staging do DayZ antes da ativação atômica; sem aplicação recursiva.
- **#963**: impedir estado online desatualizado no painel quando o runtime falha.

## Limites e exclusões
- **#964 (isolamento da DLC Nasdara/Badlands)** permanece em draft e **não integra** esta candidata.
- Nenhuma atualização automática do jogo DayZ nem restauração de persistência é autorizada por esta preparação.
- O release do DSM e a atualização de game-data são operações diferentes.

## Portões obrigatórios antes de publicar
1. CI da candidata e `tests/release_readiness_test.py`.
2. Build reproduzível, manifesto com commit exato e SHA-256 dos pacotes DSM/Linux Agent/Windows Agent.
3. Validação de compatibilidade e plano de rollback do Controller e Agent híbrido.
4. Publicação explícita em etapa separada, alterando `release/RELEASE_TRIGGER` somente após aprovação.
5. Smoke test dos artefatos públicos após publicação e instalação autorizada no `horizon-server`.
