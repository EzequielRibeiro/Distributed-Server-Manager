# Catálogo por jogo

`catalog/v2/games/` é o namespace canônico dos jogos publicados ou explicitamente adiados pelo Capivara DSM.

Os runtimes que podem ser oferecidos ao Controller/Customer ficam exclusivamente em `games/<game>/runtimes/*.json`. Um arquivo presente em `runtimes/` é considerado publicado e, portanto, deve ser executável pelos Agents declarados no próprio `RuntimeDefinition`.

## Estrutura canônica

```text
catalog/v2/games/
└── <game>/
    ├── game.json          # GameDefinition obrigatório
    ├── runtimes/          # RuntimeDefinition publicados
    ├── deferred/          # definições preservadas, mas não publicáveis
    ├── resource-profiles.json
    ├── workspace-policy.json
    └── outros dados específicos do jogo
```

Nem todo jogo precisa de todos os arquivos. Providers reutilizáveis permanecem em `catalog/v2/providers/`, schemas compartilhados em `catalog/v2/schemas/` e resolvers de versão em `installer/version_resolvers/`.

## Jogos conhecidos

Os 20 jogos publicados possuem `game.json`. Consulte `dsm catalog hierarchy --json` para a lista atual por edição e distribuição. Não há runtimes adiados nesta revisão. Luanti 5.17.0 está publicado com `http-archive` e `cmake_source`.

A lista normativa de runtimes suportados e adiados está em `catalog/v2/support-matrix.json` e é verificada pelo workflow **Catalog Completion**. O arquivo `catalog/v2/steam-top25-2026-09-03.json` registra a análise de aplicabilidade do Top 25 da Steam capturado em 3 de setembro de 2026.

## Regras de publicação

Um runtime em `runtimes/` precisa referenciar pelo campo `game` um `GameDefinition` válido no mesmo diretório de jogo, além de ter ID único, `RuntimeDefinition` v2 válido, engine/processo definidos, requisitos de SO/arquitetura, provider executável pelo Agent, Installation Strategy coerente e resolver existente quando `version.strategy=dynamic`.

Providers reservados (`local`, `custom`, `source-build`) não tornam uma definição publicável até que exista uma estratégia tipada implementada em paridade nos Agents necessários. Credenciais de terceiros também não podem ser introduzidas no catálogo, argumentos, ambiente, unidades systemd ou request JSON apenas para remover um estado `deferred`.

Project Zomboid possui bootstrap de primeira inicialização específico no Agent Linux. 7 Days to Die mantém `serverconfig.xml` no estado privado e aplica a porta por helper XML tipado. Factorio cria uma única vez o save inicial e o `server-settings.json` privados. Arma Reforger gera configuração JSON privada com portas reservadas pelo Placement. Satisfactory, Garry's Mod e Left 4 Dead 2 usam o profile nativo genérico allowlisted.

Popularidade não substitui hospedabilidade. Jogos do ranking da Steam sem distribuição pública de servidor dedicado, ou que dependem exclusivamente da infraestrutura oficial do publisher, não entram em `runtimes/` apenas para aparecer na seleção do cliente.

`Mohist` não faz parte do conjunto oficialmente publicado. `Starlight` também não é um runtime de servidor: deve ser tratado como componente de conteúdo/otimização se for incorporado futuramente.

## Separação de responsabilidades

Providers compartilhados não são duplicados por jogo. O Catalog descreve o que instalar e executar; o Agent executa apenas estratégias tipadas permitidas. Mods, plugins, modpacks e otimizações não devem ser registrados como runtimes só para aparecerem na seleção de servidor.

Consulte `catalog/v2/README.md` para o contrato de leitura hierárquica.
