# Catálogo por jogo

`catalog/v2/games/` é o namespace canônico dos jogos publicados pelo Capivara DSM.

Os runtimes que podem ser oferecidos ao Controller/Customer ficam exclusivamente em `games/<game>/runtimes/*.json`. Um arquivo presente em `runtimes/` é considerado publicado e, portanto, deve ser executável pelos Agents declarados no próprio `RuntimeDefinition`.

## Estrutura canônica

```text
catalog/v2/games/
└── <game>/
    ├── runtimes/          # RuntimeDefinition publicados
    ├── deferred/          # definições preservadas, mas não publicáveis
    ├── resource-profiles.json
    ├── workspace-policy.json
    └── outros dados específicos do jogo
```

Nem todo jogo precisa de todos os arquivos. Providers reutilizáveis permanecem em `catalog/v2/providers/`, schemas compartilhados em `catalog/v2/schemas/` e resolvers de versão em `installer/version_resolvers/`.

## Jogos conhecidos

- `arma3`
- `dayz`
- `luanti`
- `mindustry`
- `minecraft`
- `rust`

A lista normativa de runtimes suportados está em `catalog/v2/support-matrix.json` e é verificada pelo workflow **Catalog Completion**.

## Regras de publicação

Um runtime em `runtimes/` precisa ter ID único, `RuntimeDefinition` v2 válido, engine/processo definidos, requisitos de SO/arquitetura, provider executável pelo Agent, Installation Strategy coerente e resolver existente quando `version.strategy=dynamic`.

Providers reservados (`local`, `custom`, `source-build`) não tornam uma definição publicável até que exista uma estratégia tipada implementada em paridade nos Agents necessários. Definições preservadas nessas condições ficam em `deferred/`.

`Mohist` não faz parte do conjunto oficialmente publicado. `Starlight` também não é um runtime de servidor: deve ser tratado como componente de conteúdo/otimização se for incorporado futuramente.

## Separação de responsabilidades

Providers compartilhados não são duplicados por jogo. O Catalog descreve o que instalar e executar; o Agent executa apenas estratégias tipadas permitidas. Mods, plugins, modpacks e otimizações não devem ser registrados como runtimes só para aparecerem na seleção de servidor.

Consulte também `docs/architecture/game-directory-layout.md` para regras de classificação e layout.
