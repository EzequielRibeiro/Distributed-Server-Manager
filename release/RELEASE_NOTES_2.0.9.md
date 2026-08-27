# Capivara DSM 2.0.9

Esta release corrige a falha da nova administração de Agents identificada após a publicação da v2.0.8.

## Correção principal

- `AgentAdminRepository.detail()` passa a usar `issued_at`, que é o campo definido no schema oficial de `agent_credentials`, em vez do campo inexistente `created_at`.
- A correção elimina o erro PostgreSQL `UndefinedColumn: column "created_at" does not exist` que fazia a tela de detalhes do Agent retornar HTTP 500 com a mensagem `Falha ao consultar o Agent.`.
- O schema do banco não é alterado: PostgreSQL, SQLite, MySQL e MariaDB continuam usando o contrato existente de credenciais do Agent.

## Impacto operacional

Após a atualização, a página de detalhes administrativos do Agent volta a consultar normalmente os dados persistidos no Controller, inclusive quando a lista de credenciais do Agent está vazia.

Não é necessário recriar, reinstalar ou revincular o Agent para corrigir esta falha.

## Atualização

Atualize a partir da v2.0.8 usando o fluxo oficial de update do Capivara. O updater deverá detectar a v2.0.9 como versão mais recente assim que a release e seus artefatos forem publicados.

## Pacotes

Use somente os artefatos oficiais da release e valide SHA256/manifest. O pacote principal será publicado como `capivara-dsm-2.0.9.tar.gz`, acompanhado pelos pacotes Agent Linux e Windows.
