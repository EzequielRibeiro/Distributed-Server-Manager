# Capivara DSM 2.0.11

## Correção de release

- Corrige uma regressão no preflight do banco que podia transformar falha de autenticação em falso sucesso ao restaurar `DSM_ROOT` depois de executar o Database Manager.
- Preserva explicitamente o exit status de `run_database_manager` dentro de `installer/database_setup.sh` e o devolve após restaurar o contexto do instalador.
- Restaura o comportamento de bloqueio esperado quando `init` ou `check` falham durante a validação do banco.
- Desbloqueia o gate `linux_install_smoke_test.sh` usado pelo workflow oficial de release.

## Correções incluídas da tentativa 2.0.10

- Hardening do deploy remoto de Agents via SSH com `StrictHostKeyChecking=accept-new`.
- Diagnósticos específicos para autenticação SSH, host key, timeout, conexão recusada e `sudo`.
- Ownership seguro dos secrets de deploy remoto para a conta de serviço, mantendo `0700/0600`.
- Preparação de `known_hosts` da conta de serviço.
- Melhor propagação dos erros reais do bootstrap Linux Agent sem expor pairing token.
- Correções do assistente da Dashboard, rota de `test-connection` e tratamento de respostas não JSON.
- Documentação atualizada do fluxo de senha SSH e teste de conexão.

A versão 2.0.10 teve a publicação bloqueada pelo gate de validação do instalador; 2.0.11 incorpora a correção desse gate juntamente com as mudanças planejadas para 2.0.10.
