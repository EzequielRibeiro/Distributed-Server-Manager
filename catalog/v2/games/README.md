# Catálogo por jogo

`catalog/v2/games/` é o namespace canônico dos jogos publicados ou explicitamente adiados pelo Capivara DSM.

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

Publicados:

- `arma3`
- `counterstrike2`
- `dayz`
- `mindustry`
- `minecraft`
- `palworld`
- `rust`
- `teamfortress2`

Adiados com definição preservada:

- `fivem`
- `luanti`
- `projectzomboid`

A lista normativa de runtimes suportados e adiados está em `catalog/v2/support-matrix.json` e é verificada pelo workflow **Catalog Completion**. O arquivo `catalog/v2/steam-top25-2026-09-03.json` registra a análise de aplicabilidade do Top 25 da Steam capturado em 3 de setembro de 2026.

## Regras de publicação

Um runtime em `runtimes/` precisa ter ID único, `RuntimeDefinition` v2 válido, engine/processo definidos, requisitos de SO/arquitetura, provider executável pelo Agent, Installation Strategy coerente e resolver existente quando `version.strategy=dynamic`.

Providers reservados (`local`, `custom`, `source-build`) não tornam uma definição publicável até que exista uma estratégia tipada implementada em paridade nos Agents necessários. Definições preservadas nessas condições ficam em `deferred/`.

Popularidade não substitui hospedabilidade. Jogos do ranking da Steam sem distribuição pública de servidor dedicado, ou que dependem exclusivamente da infraestrutura oficial do publisher, não entram em `runtimes/` apenas para aparecer na seleção do cliente.

`Mohist` não faz parte do conjunto oficialmente publicado. `Starlight` também não é um runtime de servidor: deve ser tratado como componente de conteúdo/otimização se for incorporado futuramente.

## Separação de responsabilidades

Providers compartilhados não são duplicados por jogo. O Catalog descreve o que instalar e executar; o Agent executa apenas estratégias tipadas permitidas. Mods, plugins, modpacks e otimizações não devem ser registrados como runtimes só para aparecerem na seleção de servidor.

Consulte também `docs/architecture/game-directory-layout.md` para regras de classificação e layout.
