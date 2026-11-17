# Capivara DSM 2.0.129

Candidata de release para melhorar a descoberta do SteamCMD e a segurança do diagnóstico de instalação e atualização Steam no Agent híbrido. **Ainda não publicada.**

## Destaques

- Descoberta do SteamCMD em caminhos gerenciados e instalações existentes no ambiente híbrido, com fallback de instalação quando necessário.
- Melhor propagação de erros controlados de operações Steam ao executor híbrido, facilitando o diagnóstico de falhas de atualização do DayZ.
- Proteção dos logs de autenticação, progresso e instalação contra exposição da saída bruta do SteamCMD, incluindo dados potencialmente sensíveis.
- Preservação do código de saída do SteamCMD para identificação de falhas.

## Qualidade

- Testes de regressão para descoberta do SteamCMD, autenticação, logs de instalação e tratamento de erros do executor híbrido.
- Os 19 workflows de validação do commit final da PR #953 foram aprovados antes do merge.

## Limites e validação pendente

- A correção não altera automaticamente instâncias, mapas, mods ou arquivos do DayZ.
- A autenticação Steam e a atualização real do DayZ pelo fluxo da área do cliente ainda precisam ser validadas após implantação autorizada.
- Esta preparação não autoriza publicação de tag, release, deploy ou reinicialização de serviços.

## Origem

- PR #953 integrada à branch main no commit c503fe4ec99631d6712fd672914bf24926855aea.
