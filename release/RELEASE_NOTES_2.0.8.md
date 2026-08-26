# Capivara DSM 2.0.8

Esta release corrige regressões identificadas durante a atualização real da v2.0.6 para a v2.0.7 e reforça o contrato atual do Baseline v2.

## Correções principais

- O updater agora valida a compatibilidade do banco com o pacote alvo antes de iniciar a transação de atualização, parar serviços ou aplicar arquivos.
- Bancos inicializados com baseline/checksum incompatível são rejeitados antecipadamente, sem tentativa de migração histórica ou reescrita do `schema_baseline`.
- `database migrate` retorna código diferente de zero quando o estado final do banco é inválido.
- `cap contract create` deixa de carregar dependências do runtime de exclusão que provocavam `ModuleNotFoundError: core` em instalações Controller.
- `cap customer create` e a ajuda pública do `cap` foram alinhados ao modelo atual de IDs: o `customers.id` é gerado pelo banco e o `customer_code` público é derivado automaticamente.
- Workflows de HA/DR, Federation e Real-Time API foram alinhados ao Baseline v2 sem dependência de cadeias históricas de migration.
- Fixtures de Real-Time API foram atualizadas para o identificador numérico atual de Customer.

## Atualização segura

A atualização para esta versão executa o `database/manager.py check` do próprio pacote alvo contra o banco configurado antes de iniciar qualquer alteração na instalação. Se o baseline atual não for compatível, a atualização é interrompida antes da parada dos serviços.

O Capivara DSM continua seguindo o contrato Baseline v2: instalações novas usam o snapshot completo do schema atual e não há compatibilidade automática entre baselines históricos incompatíveis.

## Pacotes

Use somente os artefatos oficiais da release e valide SHA256/manifest. O pacote principal será publicado como `capivara-dsm-2.0.8.tar.gz`, acompanhado pelos pacotes Agent Linux e Windows.
