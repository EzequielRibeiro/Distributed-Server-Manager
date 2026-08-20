# Fase 12 — Distribuição do Linux Agent via GitHub Releases

## Objetivo

Usar GitHub Release, e nunca uma branch mutável, como canal de produção do Linux Agent.

## Fonte única

O repositório oficial continua sendo a fonte única. A tag identifica um commit imutável e os artefatos do Controller/DSM e do Agent Linux são construídos a partir desse mesmo commit.

```text
GitHub Repository
       ↓
      tag
       ↓
    Release
       ↓
capivara-agent-linux-X.Y.Z.tar.gz
       ↓
SHA-256 + manifest + GitHub provenance attestation
       ↓
remote bootstrap
```

## Artefatos

Para cada tag `vX.Y.Z`, a workflow de Release gera:

- `capivara-agent-linux-X.Y.Z.tar.gz`;
- `capivara-agent-linux-X.Y.Z.tar.gz.sha256`;
- `capivara-agent-linux-X.Y.Z.manifest.json`;
- provenance attestation publicada pelo GitHub Actions;
- opcionalmente `.minisig` quando uma chave minisign for configurada no build.

O checksum SHA-256 é obrigatório. Assinatura destacada nunca é simulada: somente existe quando uma chave real foi configurada.

## Imutabilidade e versão

`GET /agent/install.sh` é servido pelo Controller instalado e fixa `CAPIVARA_RELEASE_TAG=v<versão-do-controller>` no bootstrap. Portanto o host remoto não segue `main` e não escolhe silenciosamente outra versão.

O bootstrap consulta a GitHub Release daquela tag, seleciona somente o artefato `capivara-agent-linux-*`, baixa o `.sha256`, valida o arquivo e só então extrai e executa o instalador local contido no pacote.

## Canais

O manifest possui `channel`:

- versão SemVer sem prerelease → `stable`;
- versão SemVer com prerelease → `beta`.

A workflow já marca tags com sufixo prerelease como GitHub prerelease. A seleção explícita de canais poderá ser adicionada sem alterar o formato do pacote.

## Rollback

Rollback significa gerar/selecionar um pairing command para uma versão/tag anterior suportada ou reinstalar um pacote local correspondente. Como as Releases são imutáveis, o Controller pode conhecer precisamente a versão enviada ao Agent.

## Invariantes

1. Produção não instala de `main`.
2. O Agent package deriva do mesmo commit/tag do repositório oficial.
3. SHA-256 é validado antes da extração/instalação remota.
4. O manifest registra versão, commit, canal e hashes dos arquivos internos.
5. O pairing token e credenciais permanentes nunca fazem parte do pacote.
6. Release e instalação local usam o mesmo `install-agent.sh` e o mesmo payload runtime.
