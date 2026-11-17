# Plano de correção — parada controlada do Minecraft 005

## Bloqueio confirmado

O Controller enfileira a migração com `desired_state=stopped`. O executor do Agent, em `execute_homologated_migration`, verifica `adapter.status(record)` e rejeita estados diferentes de `inactive`/`deactivating` antes de executar o restante da transação. Isso reproduz o erro observado em 19/10/2026.

## Sequência exigida para implementação

1. Validar identidade da instância/Agent, autorização de produção, vínculo do plano imutável e confirmação explícita do cliente.
2. Fazer pré-verificações não destrutivas, incluindo espaço mínimo para backup e runtime candidato, antes de parar o serviço.
3. Obter exclusividade por instância e realizar parada controlada com timeout e confirmação de estado `inactive`; falha de parada deve abortar sem troca de arquivos.
4. Criar e verificar backup consistente da instância parada; falhas devem acionar política explícita de recuperação do estado anterior.
5. Preparar o novo NeoForge e o Server Pack, verificar hashes, trocar runtime, testar prontidão e recuperar o anterior em qualquer falha.
6. Somente após sucesso comprovado do Agent, publicar o bundle atomicamente no Controller. Em erro, sinalizar `failed` ao cliente e preservar o conteúdo para retry seguro.
7. Definir explicitamente o estado final da instância (restaurar o estado anterior, salvo escolha diferente do cliente).

## Cuidados com a implementação atual

- O código cria `baseline=_verified_backup(...)` antes do callback transacional `stop`; simplesmente inserir `adapter.stop` no callback não resolve a exigência de backup consistente nem o gate inicial.
- `execute_game_data` ocorre antes de `baseline`, então a checagem de capacidade e as garantias de parada devem ser revisadas conjuntamente, não apenas remover o gate.
- Não transformar a parada em ação do upload ou da prévia: só a confirmação da migração deve autorizar mutação.
- Validar rollback do estado de execução, não apenas a recuperação de arquivos.
- O host de testes apresentava apenas 5,5 GB livres; não contornar a verificação de capacidade.

## Homologação

Executar testes unitários e de integração em instância descartável, com adapter simulado para parada, timeout, backup inválido, falta de espaço, crash e retry. Não parar nem atualizar `cli-000001-minecraft-005` durante o desenvolvimento.

Este documento é um plano técnico, não a implementação da correção.
