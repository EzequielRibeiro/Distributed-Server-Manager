# Capivara DSM 2.0.12

Release de correção do pipeline de instalação e validação de banco de dados.

## Correções

- Preserva corretamente o código de saída do database manager durante a troca temporária de `DSM_ROOT`.
- Mantém falhas de autenticação do banco como erros bloqueantes durante a reconciliação do Baseline v2.
- Garante mensagem operacional acionável quando a conexão/autenticação ou o schema impedem a instalação.
- Mantém a ordem de reconciliação `init` seguida de `check` para bancos compatíveis com Baseline v2.

## Validação

- Correção validada na `main` pelos checks do GitHub Actions antes da criação da tag de release.
- Esta versão substitui as tentativas de publicação 2.0.10 e 2.0.11, que foram bloqueadas pelo gate de validação do instalador.
