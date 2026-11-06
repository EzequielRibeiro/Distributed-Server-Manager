# Capivara DSM 2.0.132 — Candidata pós-PR #981

**Estado:** preparação para homologação. Não publicado, sem tag `v2.0.132`, sem atualização automática do `horizon-server` e sem autorização de deploy.

## Base e correções incorporadas

Esta candidata deriva de `main` após o squash merge da **PR #981** (`8f58668e62c343dadcca4a0fd6241d58372fd71e`), sem substituir as correções posteriores à branch de homologação `release/prepare-2.0.132-rc.5`.

- **#981** — finalização segura do serverpack Minecraft NeoForge e recuperação pós-commit/restart; recuperação mutável continua **opt-in**, com habilitação explícita.
- **#986, #985** — segurança de rollback de manutenção DayZ, backup obrigatório e serialização de atualizações.
- **#980, #983** — caminho privado do BattlEye por instância e tratamento de permissões de DLC DayZ.
- **#982** — fallback de sessão Steam autenticada e tratamento de timeout.
- **#979** — regressão de retenção de backups com timestamps fiéis.
- A base `main` já incorpora **#975, #972, #968 e #967**: segurança de sessão Steam e retenção do último backup válido com histórico de 14 dias; nomes legíveis dos mods; auditoria de artefatos; detecção Workshop opt-in.

## Restrições e proteção de dados

- A implantação do DSM pode interromper instâncias gerenciadas; não pressupor o recurso de atualização sem interrupção da **#928**.
- Não iniciar migração do Minecraft 003/005 nem reinstalar mundos, mods ou dados.
- Não confundir release DSM com atualização de game-data DayZ; nenhuma atualização DayZ é autorizada por esta preparação.
- A política de descarte de arquivos de atualização temporários deve preservar logs, metadados de integridade, backups válidos e referências necessárias ao rollback.
- **#964** (isolamento automático DLC no Namalsk) e **#831** (migração entre Agents) não são declaradas concluídas por este release.
- Os E2Es Windows do núcleo transacional não equivalem a uma instalação NeoForge real em Windows.
- Host de teste atualmente observado com `2.0.132-rc.4`; não presumir equivalência binária com esta candidata.

## Portões antes de publicar

1. Validar CI de `main`/candidata, contrato `tests/release_readiness_test.py` e consistência dos metadados.
2. Construir pacotes DSM, Agent Linux e Windows do **mesmo commit aprovado**, verificar manifesto, SHA-256 e reprodutibilidade.
3. Confirmar compatibilidade/backup/rollback e parada controlada de instâncias ativas em janela apropriada.
4. Aprovar publicação explicitamente, só então alterar `release/RELEASE_TRIGGER` para `2.0.132` com marcador de publicação, sem mover tags existentes.
5. Validar artefatos públicos, smoke pós-release e atualização autorizada do `horizon-server`; deixar o mecanismo preparado para uma próxima atualização.

**Esta PR apenas prepara metadados e notas da candidata.** Não cria tag nem publica release.
