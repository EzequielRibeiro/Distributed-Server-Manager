# Capivara DSM 2.0.132-rc.5 — Candidata de homologação

**Estado:** candidata em revisão; sem autorização de publicação ou implantação.

## Integrações incluídas
- **#975:** consolida segurança da sessão SteamCMD e isolamento de instalações anônimas (#971 e #973).
- **#975:** preservação do Steam HOME e auditoria de sessão sem divulgar credenciais.
- **#975:** retenção de backups de atualização por 14 dias e último backup válido, validação estrutural de TAR/dump e correções de rollback (#974).
- **#972:** mantém os nomes legíveis dos mods Steam Workshop na interface do cliente.
- **#968:** integra política fail-closed de elegibilidade e auditoria opcional somente leitura de artefatos expirados. Não habilita descarte automático adicional.

## Restrições operacionais
- A atualização DSM ainda interrompe todas as instâncias de jogos gerenciadas que estiverem ativas; **#928 não foi implementada**.
- **#964:** isolamento automático de DLC DayZ para Namalsk ainda não integra esta candidata.
- **#967 e #831:** funcionalidades ainda em Draft não são incluídas.
- **#968:** integração de código incluída; exclusão automática global ainda requer fase adicional com validação transacional e testes E2E.
- Não confundir atualização DSM com atualização do game-data DayZ.
- A instalação ativa do `horizon-server` está identificada como `2.0.132-rc.4`; esta candidata não realiza deploy.

## Critérios antes de publicar
1. CI completa da candidata e contrato de readiness.
2. Pacotes DSM, Agent Linux e Agent Windows testados com hashes/manifests vinculados ao commit aprovado.
3. Inspeção de backup/rollback e do impacto de parada das instâncias ativas.
4. Revisão e autorização explícitas para publicação; ajustar `release/RELEASE_TRIGGER` **somente na etapa de publicação**, não nesta PR.
5. Em produção, exigir janela de manutenção aprovada até a solução de #928.
