# Capivara DSM 2.0.14

## Correções de atualização

- Corrige a validação de readiness do Dashboard durante updates para respeitar `DSM_WEB_SCHEME` e `DSM_WEB_PORT`, evitando health checks incorretos em instalações HTTPS/TLS ou em portas não padrão.
- Adiciona regressão dedicada para validar o readiness do Dashboard com transporte configurável durante a atualização.

## Baseline v2

- Adiciona o upgrade aditivo `activity_audit` ao mecanismo de Baseline v2.
- Permite reconciliar instalações Baseline v2 compatíveis que ainda não possuem a tabela de auditoria de atividades, mantendo o fluxo idempotente de upgrades aditivos.
- Amplia os testes de reconciliação para cobrir ledger ausente, upgrades pendentes e reparação da estrutura esperada sem tratar esses casos como baseline histórico incompatível.

## Validação

- O gate dedicado `Baseline Update Reconciliation` foi aprovado.
- A CI principal aprovou sintaxe Bash/PowerShell, validação Python/JavaScript, installer, instalação Linux real, updater, CLI, catálogos, builds de release, pacotes Linux/Windows e o Phase 22 final end-to-end gate.

A versão 2.0.14 substitui a tentativa 2.0.13 para o próximo teste oficial de atualização. A tag `v2.0.13` não deve ser reutilizada nem movida.
