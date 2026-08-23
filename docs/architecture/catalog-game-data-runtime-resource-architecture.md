# Catálogo, Game Data, Runtime e Perfis de Recursos

## Estado

A arquitetura está implementada de ponta a ponta nas etapas 1–10. O Catálogo é o control plane administrativo do jogo; Cliente → Contrato continua sendo a única origem de criação de instâncias.

## Regra de domínio

Quatro domínios permanecem separados:

1. **Game Catalog Definition** — define o jogo e seus runtimes.
2. **Game Data** — arquivos-base compartilhados instalados nos Agents.
3. **Runtime / Resource Profile** — define startup, templates e orçamento técnico.
4. **Instance** — materialização privada pertencente a um contrato.

O Catálogo nunca cria uma instância de cliente e o filesystem de `game-data` nunca substitui a árvore privada de uma instância.

## Game Catalog Definition

A fonte declarativa principal continua sendo `catalog/v2/games/<game>/runtimes/*.json`. O `RuntimeDefinition` define provider, versão, requisitos, artefato e processo-base. A política administrativa editável fica separada em `config/catalog-runtime/<runtime_id>.json`, preservada em reinstalações.

## Runtime Policy — Etapa 5

`CatalogRuntimePolicy` acrescenta uma camada validada sobre o `RuntimeDefinition` com:

- executable;
- argumentos como vetor, sem shell intermediário;
- working directory relativo à instância;
- environment;
- variáveis com default/required/descrição;
- shutdown (`signal`, `command` ou `stdin`);
- timeout de start e stop;
- templates de configuração confinados à instância.

Placeholders `{{VAR}}` e `${VAR}` são resolvidos no Agent. A API é `/api/catalog/runtime-policy`; leitura é administrativa e gravação exige `admin`.

## Materialização — Etapa 6

O Controller injeta `catalog_runtime_policy` e `resource_profile` no contrato de provisionamento. O Agent aplica a política ao RuntimeSpec antes da validação final. No Linux, o helper privilegiado escreve templates somente depois que a raiz da instância é materializada, mantendo contenção por path e evitando que templates sejam escritos no `game-data` compartilhado.

Variáveis derivadas automaticamente incluem `INSTANCE_ID`, `GAME_ID`, `MEMORY_MB` e portas reservadas no formato `PORT_<ROLE>`.

## Game Data — Etapa 7

O Agent aceita as operações:

- `install`;
- `update`;
- `verify`;
- `repair`;
- operações seguras de arquivos `list/read/write/create/mkdir/rename/delete/upload`.

`verify` produz um inventário limitado contendo quantidade de arquivos, bytes, digest estrutural e presença do executável esperado. `repair` reaplica o provider oficial. O File Manager limita texto a 1 MiB e upload a 32 MiB e rejeita path absoluto, traversal e escape por symlink.

## Provisionamento sob demanda — Etapa 8

```text
Cliente → Contrato → Criar Instância
                    ↓
                 Placement
                    ↓
               Agent elegível
                    ↓
          content.action = ensure
                    ↓
       game-data íntegro já existe?
          ├─ sim → reuse, sem reinstalar
          └─ não → provider instala/repara
                    ↓
         aplicar Runtime Policy
                    ↓
       materializar runtime + templates
                    ↓
       aplicar recursos + portas + config
                    ↓
                  startup
```

`catalog_provisioning_resolver.py` resolve RuntimeSelection, Runtime Policy e Resource Profile antes de enfileirar a operação. Se o contrato fornecer `allowed_resource_profiles`, qualquer perfil fora da lista é rejeitado.

## Inventário, consistência e recuperação — Etapa 9

`game_data_state.py` permanece a persistência local do Agent. `game_data_integrity.py` calcula o estado físico e `game_data_reconcile.py` reconcilia estado persistido com o filesystem, classificando bases `ok`, `missing`, `empty`, `degraded`, `unsafe` e diretórios `orphaned`.

Jobs distribuídos continuam idempotentes e os resultados finais são arquivados após a limpeza dos payloads transitórios. A combinação de `ensure`, `verify`, `repair`, state persistente e reconciliação permite recuperação após reinício sem depender de lógica especial de jogo.

## Paridade Linux / Windows — Etapa 10

Os dois Agents possuem:

- executor de Game Data;
- `ensure/install/update/verify/repair`;
- inventário de integridade;
- File Manager seguro;
- aplicação de Catalog Runtime Policy no RuntimeSpec;
- suporte aos mesmos providers já disponíveis em cada plataforma.

O build do Agent Linux inclui explicitamente os novos módulos. O build Windows descobre automaticamente todos os módulos Python em `agents/windows/runtime`.

## Perfis de recursos

Perfis ficam em `catalog/v2/games/<game>/resource-profiles.json`, por exemplo:

- Minecraft `standard`: 8192 MB RAM / 25600 MB armazenamento;
- Minecraft `large`: 16384 MB RAM / 30720 MB armazenamento.

O Catálogo determina quais perfis existem. O contrato determina quais são permitidos ao cliente. O perfil resolvido acompanha o provisionamento e é exposto ao Runtime Policy (`MEMORY_MB`) e ao Placement/runtime para enforcement dos limites.

## Dashboard

A página **Catálogo de Jogos** contém as áreas:

- Visão geral;
- Game Data;
- Parâmetros;
- Configuração;
- Recursos;
- Conteúdo;
- Agents;
- Versões.

A aba Game Data instala, atualiza, verifica, repara e manipula arquivos. Parâmetros edita a Runtime Policy. Configuração edita templates. Recursos mostra os perfis técnicos. Agents e Versões mostram disponibilidade, jobs e integridade. Nenhuma dessas áreas cria instância.

## Segurança e invariantes

- políticas persistentes são validadas antes da gravação;
- startup é vetor de argumentos, não comando shell arbitrário;
- working directory e templates não podem escapar da instância;
- Game Data File Manager não pode escapar da raiz do runtime;
- symlinks externos são recusados;
- mutações de Game Data exigem administrador no Controller;
- o Agent valida ownership da instância e identidade do Agent novamente;
- perfis fora da autorização do contrato são recusados;
- o helper privilegiado recebe somente RuntimeSpec previamente validado.

## Gate de validação

`.github/workflows/catalog-architecture.yml` valida Python, JavaScript, testes das etapas 5–10 e os pacotes Linux/Windows. A suíte principal continua cobrindo instalação real Linux, Catalog v2, pacotes e Fase 22 E2E.

## Cronograma concluído

| Etapa | Entrega | Estado |
|---|---|---|
| 1 | Auditoria e modelo de domínio | ✅ |
| 2 | Remodelagem do Catálogo | ✅ |
| 3 | Inventário de Game Data por Agent | ✅ |
| 4 | File Manager seguro de Game Data | ✅ |
| 5 | Runtime parameters / startup policy | ✅ |
| 6 | Materialização de templates e configuração | ✅ |
| 7 | Manutenção, verify e repair | ✅ |
| 8 | Provisionamento com reuse/install sob demanda | ✅ |
| 9 | Reconciliação, consistência e recuperação | ✅ |
| 10 | Paridade Linux/Windows e gate final | ✅ |
