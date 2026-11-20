# Capivara DSM 2.0.133-rc.6 — homologação DayZ/Agent (19/11/2026)

**Canal:** candidata de homologação **não publicável**, somente para build e testes isolados. Não há autorização para tag, GitHub Release, deploy ou reinício de jogos.

## Código incorporado

- **PR #1094:** corrige travessia da raiz de instância gerenciada pelo systemd do Agent externo (`StateDirectoryMode=0710`) e reconciliação restrita, idempotente e sem reiniciar um processo já ativo.
- **PR #1095:** corrige a ampliação indevida de permissões DayZ quando `files_root=instance_state_root`. Mantém raiz `0710`, árvore `.dsm` privada, conteúdo UCP sob sua própria política e navegação virtual do cliente para diretórios autorizados. Bloqueia caminhos forjados e mutações das entradas de primeiro nível.
- Base do código: `e0d451105573032ba0276351cc8604bab454dccc`. A versão do pacote deve identificar o commit completo do checkout candidato, incluindo atualização do arquivo `version`.

## Critérios de homologação

1. Gerar pacote em checkout isolado com `release/build_release.sh <commit-candidato> <saida>`; conferir SHA-256, manifesto, versão e arquivos incluídos.
2. Executar testes de permissões Agent, isolamento DayZ, file-manager e systemd real apenas em instalações **descartáveis**.
3. Para o Horizon, a instalação atual reportada pelo Codex é `2.0.133-rc.4` (manifesto `df992920a07a7d951160c877c3851373deea1ba4`). Comparar dados, arquivos, backups e configurações antes e depois apenas num **clone isolado**; não presumir acesso aos caminhos protegidos a partir da identidade SSH sem privilégios.
4. Verificar em uma instalação de teste: raiz DayZ `0710`, `.dsm` `0700/0600`, `content/workshop` com identidade correta e acessível ao Agent, navegação virtual e leitura/escrita legítima de `config/serverDZ.cfg`.

## Bloqueios

- **Preservação de PIDs:** `update.sh` pode reiniciar Controller, Workers e jogos ativos; rollback também pode reiniciar jogos. **NÃO executar o updater no Horizon** enquanto for necessário preservar os PIDs dos servidores DayZ.
- `--no-drain` e `--no-drain-report` são apenas diagnósticos; não aplicam a atualização.
- **Backups:** auditar solicitações `backup_jobs` pendentes e assegurar preservação do último backup restaurável antes de qualquer atualização; não presumir que o dispatcher revalida universalmente o último backup.
- Não modificar manualmente as permissões para mascarar a regressão, não executar `chown -R` ou `chmod -R` e não alterar jogos em produção.
- A issue #977 permanece aberta até evidência real pós-implantação, incluindo validação do fluxo do usuário na VPS e no Hybrid.

**Publicação:** esta candidata está marcada `publish_release=false`, `release_authorized=false`; `release/RELEASE_TRIGGER` não deve ser alterado nesta etapa. O gate de publicação deve permanecer fechado até autorização expressa.
