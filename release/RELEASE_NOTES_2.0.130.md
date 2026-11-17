# Capivara DSM 2.0.130

Candidata de release para disponibilizar controles de atualização do servidor de jogo na área do cliente. **Não publicada.**

## Destaques

- Botões **Verificar atualizações** e **Atualizar servidor** no painel do cliente, com confirmação explícita antes da atualização.
- Operações restritas à permissão `instance.update` da instância.
- Bloqueio de solicitações simultâneas e exigência de estado `update_available` para atualização manual.
- Indicador público de operação em andamento sem exposição de identificadores internos.
- Integração com o mecanismo universal de atualização do Controller/Agent híbrido, sem alteração automática das instâncias.

## Qualidade

- PR #956 integrada à `main` no commit `52e256d3d39bb16db64f5fd1316d5a9cb28ac38f`.
- 26 workflows aprovados na revisão final da PR.
- 42 testes locais da suíte ampliada aprovados; teste adicional de concorrência com PostgreSQL 16 isolado aprovado.

## Limites

- Preparação de candidata: publicação de tag, GitHub Release e deploy **não autorizados por esta alteração**.
- O DayZ não é atualizado durante o release do DSM; a atualização real deverá ser solicitada pela área do cliente após implantação autorizada.
- Teste funcional de ponta a ponta pela área do cliente permanece pendente.
