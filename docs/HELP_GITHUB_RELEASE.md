# Ajuda — Como criar e publicar uma Release no GitHub

Este documento descreve o procedimento oficial para preparar e publicar uma nova release do **Capivara Distributed Server Manager** no GitHub.

O fluxo atual publica três releases relacionadas à mesma versão:

1. **Release principal do Capivara DSM** — tag `vX.Y.Z`.
2. **Agent Linux standalone** — tag `agent-linux-vX.Y.Z`.
3. **Agent Windows standalone** — tag `agent-windows-vX.Y.Z`.

> Exemplo usado neste tutorial: `2.0.22`. Para uma nova versão, substitua `2.0.22` pela versão desejada.

---

## 1. Pré-requisitos

Antes de publicar uma release:

- trabalhe a partir da branch `main` atualizada;
- confirme que as alterações destinadas à versão já foram integradas em `main`;
- confirme que os workflows importantes de CI estão verdes;
- não reutilize uma versão já publicada para um conteúdo diferente;
- confirme que a versão escolhida segue o formato semântico `MAJOR.MINOR.PATCH`, por exemplo `2.0.23`.

No computador de desenvolvimento:

```bash
git checkout main
git pull --ff-only origin main
git status
```

O `git status` deve estar limpo antes de preparar os arquivos da release.

---

## 2. Definir a versão do projeto

A versão canônica fica no arquivo:

```text
version
```

Para publicar, por exemplo, a versão `2.0.23`, o conteúdo deve ser exatamente:

```text
2.0.23
```

Confira:

```bash
cat version
```

---

## 3. Atualizar o manifesto de readiness

Edite:

```text
release/readiness-v2.json
```

Os campos de versão precisam acompanhar o arquivo `version`:

```json
{
  "release_version": "2.0.23",
  "tag_name": "v2.0.23",
  "status": "release-approved",
  "publish_release": false,
  "release_authorized": true
}
```

### Regras importantes

O contrato atual de release exige, entre outras coisas:

- `schema_version` igual a `1`;
- `release_line` igual a `2.0` enquanto estivermos na linha 2.0;
- `release_version` igual ao conteúdo de `version`;
- `tag_name` igual a `v` + versão;
- `publish_release` igual a `false`;
- `release_authorized` igual a `true`;
- todos os gates obrigatórios existentes preservados;
- todas as capabilities obrigatórias existentes preservadas;
- paridade de schema para SQLite, PostgreSQL e MySQL/MariaDB preservada.

Não remova gates ou capabilities apenas para fazer o teste passar.

---

## 4. Criar as notas da release

Crie um arquivo no formato:

```text
release/RELEASE_NOTES_X.Y.Z.md
```

Para `2.0.23`:

```text
release/RELEASE_NOTES_2.0.23.md
```

A primeira linha deve conter o nome e a versão esperados pelo contrato de readiness:

```markdown
# Capivara DSM 2.0.23
```

Estrutura recomendada:

```markdown
# Capivara DSM 2.0.23

Resumo da release.

## Destaques

- Alteração importante 1.
- Alteração importante 2.
- Alteração importante 3.

## Catálogo e runtimes

- Novos jogos, engines ou runtimes.

## Agents

- Alterações do Agent Linux.
- Alterações do Agent Windows.

## Rede e Placement

- Mudanças em portas, NAT, IPv6, Placement ou capabilities.

## Segurança e confiabilidade

- Hardening, autenticação, autorização, lifecycle e recuperação.

## Qualidade

- Testes e workflows adicionados ou ampliados.
```

### Atenção

O teste `tests/release_readiness_test.py` procura literalmente a expressão:

```text
Capivara DSM X.Y.Z
```

Se as notas usarem apenas `vX.Y.Z`, outro título ou outra grafia, a validação pode falhar.

---

## 5. Validar localmente antes da publicação

Execute pelo menos o contrato de release:

```bash
python3 tests/release_readiness_test.py
```

Resultado esperado:

```text
P9 release readiness contract: OK (2.0.23)
```

Também é recomendável validar sintaxe e arquivos estruturados:

```bash
git ls-files -z '*.sh' | xargs -0 -n1 bash -n
find catalog games -type f -name '*.json' -print0 | xargs -0 -n1 jq empty
```

Para reproduzir a parte mais ampla do workflow de release, consulte:

```text
.github/workflows/release.yml
```

O próprio workflow executa a suíte oficial antes de criar os artefatos de uma publicação iniciada por tag.

---

## 6. Revisar o que será publicado

Antes de disparar a release:

```bash
git diff
git status
```

Confirme principalmente:

```text
version
release/readiness-v2.json
release/RELEASE_NOTES_X.Y.Z.md
```

Se houver mudanças adicionais, confirme que elas realmente pertencem à release.

---

## 7. Commitar a preparação da versão

Exemplo:

```bash
git add version \
  release/readiness-v2.json \
  release/RELEASE_NOTES_2.0.23.md

git commit -m "Prepare Capivara DSM v2.0.23"
git push origin main
```

Depois do push, acompanhe os checks de `main` e confirme que não existem regressões bloqueantes.

---

## 8. Disparar explicitamente a publicação

A publicação é disparada pelo arquivo:

```text
release/RELEASE_TRIGGER
```

A **primeira linha** desse arquivo precisa ser exatamente a versão atual, sem `v`:

```text
2.0.23
```

Pode existir informação adicional nas linhas seguintes, mas a primeira linha é o valor validado pelo workflow.

Exemplo:

```text
2.0.23
publish=2026-09-04T10:00:00-03:00
```

Depois:

```bash
git add release/RELEASE_TRIGGER
git commit -m "Publish Capivara DSM v2.0.23"
git push origin main
```

Esse push em `main` inicia o job `orchestrate` do workflow `.github/workflows/release.yml`.

---

## 9. O que o workflow faz automaticamente

Ao detectar a alteração de `release/RELEASE_TRIGGER`, o workflow executa a sequência abaixo.

### 9.1 Valida o gatilho

Ele compara:

```text
version
```

com a primeira linha de:

```text
release/RELEASE_TRIGGER
```

Em seguida executa:

```bash
python3 tests/release_readiness_test.py
```

Também confirma que existe:

```text
release/RELEASE_NOTES_X.Y.Z.md
```

### 9.2 Gera o Agent Linux standalone

O pacote é criado pelo script:

```text
release/build_agent_package.sh
```

Artefatos esperados:

```text
capivara-agent-linux-X.Y.Z.tar.gz
capivara-agent-linux-X.Y.Z.tar.gz.sha256
capivara-agent-linux-X.Y.Z.manifest.json
```

### 9.3 Gera o Agent Windows standalone

O pacote é criado por:

```text
release/build_windows_agent_package.py
```

Artefatos esperados:

```text
capivara-agent-windows-X.Y.Z.zip
capivara-agent-windows-X.Y.Z.zip.sha256
capivara-agent-windows-X.Y.Z.manifest.json
```

### 9.4 Publica o Agent Linux separadamente

Cria a release:

```text
agent-linux-vX.Y.Z
```

Título:

```text
Capivara Agent Linux vX.Y.Z
```

Essa release contém somente os arquivos standalone do Agent Linux.

### 9.5 Publica o Agent Windows separadamente

Cria a release:

```text
agent-windows-vX.Y.Z
```

Título:

```text
Capivara Agent Windows vX.Y.Z
```

Essa release contém somente os arquivos standalone do Agent Windows.

### 9.6 Posiciona a tag canônica da release

A tag principal é:

```text
vX.Y.Z
```

Ela deve apontar para o commit aprovado que contém a preparação final da publicação.

### 9.7 Publica a release principal

A release principal recebe o título:

```text
Capivara DSM vX.Y.Z
```

As notas vêm de:

```text
release/RELEASE_NOTES_X.Y.Z.md
```

Ela pode conter:

- pacote completo do Capivara;
- checksum do pacote principal;
- manifesto;
- pacote Agent Linux;
- checksum e manifesto Linux;
- pacote Agent Windows;
- checksum e manifesto Windows.

Mesmo que os Agents apareçam também na release principal, as releases `agent-linux-*` e `agent-windows-*` existem para permitir distribuição standalone e URLs independentes.

---

## 10. Como verificar a publicação no GitHub

Abra a página de releases:

```text
https://github.com/EzequielRibeiro/Distributed-Server-Manager/releases
```

Para uma versão `2.0.23`, devem existir três publicações:

```text
v2.0.23
agent-linux-v2.0.23
agent-windows-v2.0.23
```

Links previsíveis:

```text
https://github.com/EzequielRibeiro/Distributed-Server-Manager/releases/tag/v2.0.23
https://github.com/EzequielRibeiro/Distributed-Server-Manager/releases/tag/agent-linux-v2.0.23
https://github.com/EzequielRibeiro/Distributed-Server-Manager/releases/tag/agent-windows-v2.0.23
```

---

## 11. Verificar os artefatos

Na release Linux, confirme a presença de:

```text
capivara-agent-linux-X.Y.Z.tar.gz
capivara-agent-linux-X.Y.Z.tar.gz.sha256
capivara-agent-linux-X.Y.Z.manifest.json
```

Na release Windows:

```text
capivara-agent-windows-X.Y.Z.zip
capivara-agent-windows-X.Y.Z.zip.sha256
capivara-agent-windows-X.Y.Z.manifest.json
```

Na release principal, confirme os artefatos esperados do Capivara e dos Agents.

---

## 12. Validar SHA-256 após baixar

### Linux

```bash
sha256sum -c capivara-agent-linux-X.Y.Z.tar.gz.sha256
```

### Windows PowerShell

```powershell
Get-FileHash .\capivara-agent-windows-X.Y.Z.zip -Algorithm SHA256
```

Compare o valor retornado com o arquivo:

```text
capivara-agent-windows-X.Y.Z.zip.sha256
```

Nunca distribua um pacote que não corresponda ao checksum publicado.

---

## 13. Não criar a tag manualmente antes da hora

O fluxo oficial administra a tag canônica durante a publicação.

Evite executar antecipadamente:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Uma tag criada prematuramente pode apontar para um commit anterior à preparação final e gerar uma release inconsistente.

Se uma tag já existir, verifique o commit para o qual ela aponta antes de qualquer correção.

---

## 14. Troubleshooting

### Erro: `AssertionError` em `release_readiness_test.py`

Confira, nesta ordem:

```bash
cat version
head -n1 release/RELEASE_TRIGGER
cat release/readiness-v2.json
head release/RELEASE_NOTES_X.Y.Z.md
```

Os valores precisam estar coerentes.

### Erro porque as notas não contêm a versão

A release note deve conter literalmente:

```text
Capivara DSM X.Y.Z
```

Exemplo correto:

```markdown
# Capivara DSM 2.0.23
```

### `RELEASE_TRIGGER` diferente de `version`

Errado:

```text
version: 2.0.23
RELEASE_TRIGGER: v2.0.23
```

Correto:

```text
version: 2.0.23
RELEASE_TRIGGER: 2.0.23
```

A tag recebe `v`; o arquivo de versão e o trigger não.

### Release dos Agents não apareceu

No GitHub Actions, abra o workflow **Release** e verifique o step:

```text
Publish standalone Linux and Windows Agent releases
```

Antes dele, o step:

```text
Build standalone Agent installers
```

precisa ter terminado com sucesso.

### A release principal não apareceu

Confirme se estes steps foram concluídos:

```text
Validate explicit release trigger
Build standalone Agent installers
Publish standalone Linux and Windows Agent releases
Move canonical release tag to approved release commit
Publish canonical GitHub Release
```

### Uma tag já existe

Não apague ou mova uma tag publicada sem primeiro verificar se existem instalações, atualizadores ou links externos consumindo essa versão.

Tags de release são parte do contrato de distribuição.

---

## 15. Checklist oficial antes do botão verde

Use este checklist para cada nova versão:

```text
[ ] main atualizada e limpa
[ ] mudanças da versão integradas em main
[ ] CI relevante verde
[ ] arquivo version atualizado
[ ] release/readiness-v2.json atualizado
[ ] release_authorized = true
[ ] publish_release = false
[ ] tag_name = vX.Y.Z
[ ] RELEASE_NOTES_X.Y.Z.md criado
[ ] notas contêm "Capivara DSM X.Y.Z"
[ ] tests/release_readiness_test.py passa localmente
[ ] JSONs e scripts validados
[ ] commit de preparação enviado para main
[ ] checks do commit de preparação revisados
[ ] primeira linha de RELEASE_TRIGGER = X.Y.Z
[ ] commit de publicação enviado para main
[ ] workflow Release concluído com sucesso
[ ] release vX.Y.Z publicada
[ ] release agent-linux-vX.Y.Z publicada
[ ] release agent-windows-vX.Y.Z publicada
[ ] checksums e manifests presentes
[ ] links de download testados
```

---

## 16. Exemplo resumido — próxima versão

Supondo que a próxima versão seja `2.0.23`:

```bash
git checkout main
git pull --ff-only origin main

# editar version -> 2.0.23
# editar release/readiness-v2.json -> 2.0.23 / v2.0.23
# criar release/RELEASE_NOTES_2.0.23.md

python3 tests/release_readiness_test.py

git add version release/readiness-v2.json release/RELEASE_NOTES_2.0.23.md
git commit -m "Prepare Capivara DSM v2.0.23"
git push origin main

# aguardar/revisar os checks de main
# depois atualizar release/RELEASE_TRIGGER, primeira linha = 2.0.23

git add release/RELEASE_TRIGGER
git commit -m "Publish Capivara DSM v2.0.23"
git push origin main
```

Depois, acompanhe **Actions → Release** até o job `orchestrate` terminar com sucesso e confirme as três releases no GitHub.

---

## 17. Arquivos que formam o contrato de release

Os arquivos mais importantes são:

```text
version
release/readiness-v2.json
release/RELEASE_TRIGGER
release/RELEASE_NOTES_X.Y.Z.md
.github/workflows/release.yml
tests/release_readiness_test.py
release/build_release.sh
release/build_agent_package.sh
release/build_windows_agent_package.py
```

Antes de alterar o processo de publicação, revise esses arquivos em conjunto. Uma mudança isolada pode quebrar a criação da release principal, dos Agents standalone ou a validação de readiness.

---

## 18. Regra operacional

O padrão oficial de distribuição do Capivara é:

```text
Capivara DSM vX.Y.Z
├── release principal
├── Agent Linux incluído nos artefatos
└── Agent Windows incluído nos artefatos

Capivara Agent Linux vX.Y.Z
└── distribuição Linux standalone

Capivara Agent Windows vX.Y.Z
└── distribuição Windows standalone
```

Essa separação deve ser preservada nas próximas releases, salvo mudança deliberada do contrato de distribuição e do workflow oficial.
