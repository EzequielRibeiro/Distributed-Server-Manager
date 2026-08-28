# Capivara DSM 2.0.13

## Update reliability

- Corrige o preflight de atualização para distinguir incompatibilidade real de banco de uma reconciliação Baseline v2 suportada.
- Permite que um banco no mesmo Baseline v2, com checksum compatível e ledger de upgrades ainda pendente, prossiga até a etapa segura de migração.
- Mantém o Process Guard estritamente read-only: nenhuma alteração de banco ocorre antes da parada controlada dos serviços.
- Corrige `DatabaseBackend.migrate()` nos backends Baseline v2 para aplicar/reconciliar upgrades aditivos registrados, em vez de apenas validar o estado atual.
- Preserva o bloqueio para baselines diferentes, estruturas incompletas, ledgers inválidos e checksums pre-ledger não reconhecidos.

## Regression coverage

- Adiciona teste reproduzindo o caminho de atualização de uma instalação Baseline v2 sem `baseline_upgrades` para o ledger atual.
- Adiciona gate de CI específico para reconciliação do banco durante updates.
- O workflow de release passa a executar o teste de regressão antes de publicar artefatos.

## Upgrade path

Esta release é destinada também a instalações 2.0.9 que encontraram o bloqueio de compatibilidade ao tentar atualizar para 2.0.12. O updater continua criando backup consistente antes da transação e mantém rollback automático em caso de falha posterior.
