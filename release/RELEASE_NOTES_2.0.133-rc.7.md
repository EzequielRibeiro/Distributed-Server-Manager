# Capivara DSM 2.0.133-rc.7 — candidata de homologação (20/11/2026)

**Status:** homologation-only. Não autorizada para publicação, tag, merge da PR de homologação ou instalação em produção. Arquivo de readiness: `publish_release=false` e `release_authorized=false`. `release/RELEASE_TRIGGER` não foi alterado.

## Base e mudanças incorporadas

Esta candidata toma a `main` após o squash da PR **#1102** (`da6651a891b1abb8aa8f73def0265066e3e47681`) e da PR **#1089** (`120ef2b50947569e327f79cadfcf78bb59405600`). Também incorpora as correções anteriores #1094 e #1095.

- **#1102:** backup protegido do Agent com helper privilegiado de escopo limitado, prevenção de tentativas automáticas infinitas, política de acesso funcional a arquivos do DayZ, dependências de mods/mapas e reparo idempotente das permissões do keyring `.bikey`.
- **#1089:** nomes distintos para missões comunitárias Namalsk Regular e Hardcore no inventário da área do cliente.
- **#1094 / #1095:** travessia funcional da raiz privada do Agent e isolamento DayZ sem ampliar permissões de `.dsm` ou dos dados de outros clientes.

O preview do **Agent** `2.0.133-rc.6.pr1102.4` já foi instalado e homologado em VPS para a correção #1102. Isso **não representa** implantação do pacote completo **DSM** `2.0.133-rc.7`.

## Evidência existente

- CI da PR #1102: 37/37 verificações aprovadas; CI da PR #1089: 12/12.
- VPS DayZ 002: missão `hardcore.namalsk`, CF/VPP/Namalsk Island/Survival na linha de comando, chaves públicas legíveis pelo processo do jogo; jogador Hackuso autenticou e teve personagem, posição e uma sessão de aproximadamente 25 minutos registrados sem reincidência do erro `0x00040074`.
- Desconexão final de código 4 (conexão com o host perdida) é ocorrência distinta a monitorar se recorrente.

## Gate antes de qualquer implantação do DSM

1. Build exato do commit candidato com `release/build_release.sh <sha> <out>`; validar SHA-256, manifestos, conteúdo do TAR e versão do arquivo `version`. O workflow específico da PR gera artefato efêmero e **não publica release**.
2. Executar testes de integração do Controller, Workers e Agent e ensaiar rollback em ambiente descartável; conferir preservação de banco, arquivos e backups.
3. Homologar a **criação de um backup real pelo novo helper privilegiado** e comprovar integridade/restaurabilidade do TAR. Uma listagem íntegra de TAR prévio **não substitui restore completo**.
4. **Preservar PIDs de jogos ativos no Horizon**: não executar `sudo /opt/dsm/update.sh` até comprovar operação transacional sem drenagem ou autorizar janela específica com impacto conhecido. A ação `--no-drain` apenas diagnostica.
5. Validar após atualização em teste o fluxo da área do cliente, incluindo nomes dos mapas Regular/Hardcore, acesso a arquivos legítimos e fronteiras de isolamento.

**Sem autorização expressa:** não alterar `release/RELEASE_TRIGGER`, não ativar `release_authorized`, não criar tag/release, não efetuar implantação no Horizon nem interromper jogos.
