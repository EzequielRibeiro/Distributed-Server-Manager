# Capivara DSM 2.0.25

Hotfix de compatibilidade do Database Baseline v2 para atualizações de instalações 2.0.x existentes.

## Correções

- Corrige a falha observada no upgrade PostgreSQL **2.0.14 -> 2.0.24**, em que o preflight aceitava a reconciliação do Baseline v2, mas o migrador abortava depois da parada controlada dos serviços com `Database Baseline v2 checksum differs but no registered upgrade is pending`.
- Registra o upgrade aditivo **Baseline v2 upgrade 6 — `universal_server_update`**.
- Materializa de forma controlada as tabelas `instance_update_policy`, `instance_update_state` e `instance_update_runs` quando um banco com ledger v5 é atualizado para o baseline atual.
- Mantém o fluxo idempotente quando as três tabelas já existem.
- Rejeita estado parcial das tabelas de atualização de servidores em vez de marcar silenciosamente o baseline como reconciliado.
- Atualiza os testes de reconciliação Baseline v2 e o gate de implantação PostgreSQL isolada para o ledger v6.
- Adiciona regressão reproduzindo checksum histórico + ledger v5 + upgrade v6 pendente.
- Atualiza o teste de build reproduzível para validar exatamente esse caminho de atualização.

## Segurança e rollback

- A correção não ignora divergência de checksum nem substitui o marcador do baseline sem uma evolução registrada no ledger.
- A migração continua fail-closed para schemas parciais ou caminhos de upgrade não reconhecidos.
- O backup consistente do banco e o rollback de arquivos/serviços existentes permanecem inalterados.

## Orientação de atualização

Instalações em `2.0.14` ou outra versão 2.0.x anterior devem atualizar diretamente para `2.0.25` usando:

```bash
sudo cap update run
```

A atualização esperada deve mostrar o ledger avançando de **v5 para v6** antes de concluir a reconciliação do checksum do Baseline v2.
