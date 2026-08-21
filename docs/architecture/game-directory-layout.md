# Organização canônica dos jogos

## Objetivo

Reduzir a dispersão de arquivos que descrevem o mesmo jogo sem quebrar os contratos atuais do catálogo, Runtime, Dashboard ou instaladores.

A reorganização é incremental, porém a migração dos **RuntimeDefinitions distribuídos pelo repositório foi concluída para todos os jogos atuais**.

## Princípio

**Tudo que descreve um jogo pertence ao domínio daquele jogo. Tudo que implementa um mecanismo reutilizável permanece compartilhado.**

Exemplos:

- identidade, capabilities, requisitos de rede e runtimes: específicos do jogo;
- Steam, HTTP archive, GitHub Releases e Modrinth: providers reutilizáveis;
- schemas: contratos compartilhados;
- adaptadores de processo: código operacional específico do jogo, mantido no diretório de nível superior `games/`.

## Estrutura atual do catálogo de runtimes

```text
catalog/v2/
├── games/
│   ├── arma3/
│   │   └── runtimes/
│   ├── dayz/
│   │   └── runtimes/
│   ├── luanti/
│   │   └── runtimes/
│   ├── mindustry/
│   │   └── runtimes/
│   ├── minecraft/
│   │   └── runtimes/
│   └── rust/
│       └── runtimes/
├── content/
├── providers/
├── schemas/
└── examples/
```

O caminho canônico de um RuntimeDefinition é:

```text
catalog/v2/games/<game>/runtimes/<variant>.json
```

A árvore anterior `catalog/v2/runtimes/` não faz mais parte do catálogo distribuído pelo repositório.

## Estrutura futura por jogo

Cada diretório poderá evoluir, conforme necessidade real, para:

```text
catalog/v2/games/<game>/
├── game.json
├── runtimes/
├── content/
├── network.json
└── capabilities.json
```

Nem todo jogo precisa possuir todos esses arquivos. A criação de novos manifests deve ocorrer apenas quando houver informação canônica que justifique essa separação.

## Responsabilidade do diretório de nível superior `games/`

O diretório `games/` na raiz do repositório continua reservado a código/adaptadores operacionais de processo. Ele não é uma segunda fonte de verdade para descoberta do catálogo.

```text
games/<game>/
└── adaptador de execução, launcher e integração operacional
```

Metadados declarativos pertencem ao catálogo; comportamento operacional pertence aos adaptadores.

## Classificação usada durante a reorganização

- **CANÔNICO** — fonte de verdade declarativa do jogo;
- **ESPECÍFICO DO JOGO** — comportamento necessário apenas para um jogo;
- **REUTILIZÁVEL** — mecanismo compartilhado por vários jogos;
- **DUPLICADO** — informação já representada por outra fonte canônica;
- **LEGADO** — mantido apenas por compatibilidade e candidato à remoção futura.

## Compatibilidade de caminhos

A resolução de runtimes é centralizada em `installer/catalog_paths.sh`.

O catálogo do próprio repositório usa somente o namespace canônico. Entretanto, para não quebrar catálogos externos, fixtures antigas ou atualizações em transição, o resolvedor ainda aceita:

```text
catalog/v2/runtimes/<game>/<variant>.json
```

como fallback de leitura.

Quando os dois layouts estão presentes em um catálogo externo, a definição em:

```text
catalog/v2/games/<game>/runtimes/<variant>.json
```

tem precedência, e listagens eliminam duplicações por `id`.

Os comandos `runtime list`, `runtime show` e `runtime prepare` usam essa mesma camada. O Dashboard e o CompatibilityResolver também compartilham o resolvedor Bash, enquanto consumidores Python usam `core/catalog_runtime_paths.py` com o mesmo contrato canônico-first.

## Migração realizada

### Piloto

DayZ foi usado para validar a estratégia completa antes da migração em massa:

1. inventário dos consumidores;
2. resolvedor canônico + fallback;
3. testes legacy-only e canonical-only;
4. precedência e deduplicação;
5. movimentação física do manifesto;
6. regressão do Dashboard, instalação, placement e catálogo.

### Todos os jogos atuais

Após o piloto, foram migrados:

- Arma 3 — `arma3.stable`;
- DayZ — `dayz.stable`;
- Luanti — `luanti.stable`;
- Mindustry — `mindustry.github`;
- Minecraft — `minecraft.bedrock.vanilla`, `minecraft.java.vanilla`, `minecraft.java.paper`, `minecraft.java.fabric` e `minecraft.java.arclight`;
- Rust — `rust.stable`.

Os manifests foram preservados, incluindo provider, package/App ID, executável, versão/resolver, requisitos de plataforma e política de rede existente.

## Testes de proteção

`tests/catalog_path_resolver_test.sh` verifica:

1. leitura de catálogo legacy-only externo;
2. leitura canonical-only;
3. precedência canônica em coexistência;
4. deduplicação por runtime ID;
5. `runtime prepare` usando o mesmo resolvedor;
6. presença única de todos os runtime IDs distribuídos;
7. ausência da árvore `catalog/v2/runtimes/` no repositório.

O workflow `Catalog Layout Compatibility` executa esse contrato e em seguida a regressão `tests/catalog_v2_test.sh`. O CI principal continua validando instalação, Dashboard, Python, Agents e o gate end-to-end.

## Próximas etapas estruturais

A conclusão da migração dos runtimes não significa mover automaticamente todos os outros arquivos. As próximas etapas devem ser independentes e protegidas por testes:

- introduzir uma identidade canônica `game.json` se ela eliminar duplicação real;
- disponibilizar uma listagem canônica de jogos sem deduzi-la apenas dos runtimes;
- avaliar a migração de `content/` para o namespace por jogo;
- comparar `game.conf` e manifests canônicos antes de remover duplicações;
- mover fixtures de providers que hoje vivem sob `games/` para uma área de testes apropriada;
- retirar fallback legado somente quando não houver necessidade de compatibilidade externa.

## Regra para novos jogos

Novos jogos devem criar seus RuntimeDefinitions diretamente em:

```text
catalog/v2/games/<game>/runtimes/
```

Não deve ser recriada a árvore `catalog/v2/runtimes/`. Mecanismos genéricos devem ser reutilizados em vez de copiados para cada jogo.
