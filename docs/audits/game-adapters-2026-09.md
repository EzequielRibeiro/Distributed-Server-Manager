# Auditoria de adaptadores `games/`

Status: concluída para o cleanup arquitetural das etapas 8–13.

Base auditada: `main` em `07a66ac7e690de9db238ef2abf189cfc520c9cb4`.

## Limite arquitetural confirmado

`catalog/v2/games/` é a fonte única de verdade para descoberta e instalação: GameDefinition, RuntimeDefinition, providers, versões, builds, requisitos e plataformas.

O `games/` da raiz ainda contém adaptadores shell realmente consumidos. `core/game_loader.sh` resolve `${DSM_ROOT}/games/${GAME_ID}` e exige `runtime.sh` para o caminho que carrega um adaptador completo; `server/start.sh` também resolve `games/${GAME}/runtime.sh`. Ao mesmo tempo, a auditoria encontrou entradas históricas contendo somente `game.conf`. Por isso o namespace atual é misto: adaptadores operacionais completos e configuração de compatibilidade. Remover o diretório ou os adaptadores completos quebraria caminhos ainda suportados.

## Classificação

| Diretório | Classificação | Decisão |
| --- | --- | --- |
| `games/arma3` | adaptador operacional completo (`runtime.sh`) | manter |
| `games/dayz` | adaptador operacional completo (`runtime.sh`) | manter |
| `games/luanti` | configuração histórica/compatibilidade (`game.conf` somente) | manter até migração explícita dos consumidores de configuração |
| `games/mindustry` | configuração histórica/compatibilidade (`game.conf` somente) | manter até migração explícita dos consumidores de configuração |
| `games/minecraft` | adaptador operacional agregador (`runtime.sh`, Java/Bedrock) | manter |
| `games/minecraft-java` | configuração histórica Java (`game.conf` somente) | manter por compatibilidade; não fundir sem migração de ID/consumidores |
| `games/rust` | adaptador operacional completo (`runtime.sh`) | manter |
| `games/custom-provider-test` | fixture de provider | mover para testes |
| `games/github-provider-test` | fixture de provider | mover para testes |
| `games/http-fail-test` | fixture negativa de provider | mover para testes |
| `games/http-provider-test` | fixture de provider | mover para testes |
| `games/local-provider-test` | fixture de provider | mover para testes |

## Minecraft x Minecraft Java

As duas entradas não são equivalentes no estado atual. `games/minecraft/game.conf` declara o jogo agregador `minecraft`, com edições `java bedrock`, provider dinâmico e defaults gerais, e o diretório possui `runtime.sh`. `games/minecraft-java/game.conf` declara a identidade histórica `minecraft-java`, uma versão Java fixa e contrato HTTP reproduzível, mas não possui `runtime.sh`. A coexistência é dívida de compatibilidade; a remoção/fusão sem migração poderia quebrar consumidores que ainda referenciem `minecraft-java`. Decisão: preservar ambos neste cleanup e tratar a convergência como migração separada.

## Instalação em `game.conf`

Várias entradas ainda carregam campos históricos como `INSTALL_PROVIDER`, `INSTALL_PACKAGE_ID`, `GAME_VERSION` e `GAME_BUILD`. Esses valores não podem competir com Catalog v2. O contrato foi documentado: são apenas dados de compatibilidade enquanto algum caminho legado precisar deles; Catalog v2 continua sendo a autoridade de descoberta/instalação.

## Fixtures removidas do namespace de produção

Os cinco falsos jogos de provider foram preservados em `tests/fixtures/game-adapters/<fixture>/game.conf` e removidos de `games/`. Isso evita que scans/consumidores do namespace de produção confundam testes com jogos reais sem perder material de regressão.

## Dívidas identificadas, não removidas neste cleanup

- `server/process.sh` contém lógica DayZ em uma superfície genericamente nomeada; mover/remover exige auditoria própria de consumidores.
- `minecraft-java` pode ser convergido ao modelo hierárquico `minecraft`, mas somente com migração explícita de compatibilidade.
- campos de instalação em `game.conf` devem desaparecer gradualmente à medida que consumidores de compatibilidade forem migrados para RuntimeDefinition/Runtime Profile.
- `luanti` e `mindustry` são entradas config-only, não adaptadores completos; podem futuramente sair de `games/` quando não houver consumidor legado de seus `game.conf`.

## Guardas adicionados

`tests/game_adapter_architecture_test.py` impede o retorno dos cinco provider fixtures para `games/`, exige `runtime.sh` somente dos adaptadores completos conhecidos (`arma3`, `dayz`, `minecraft`, `rust`), registra explicitamente as entradas config-only (`luanti`, `mindustry`, `minecraft-java`) e valida que a documentação aponta para `catalog/v2/games/<game>/runtimes/`.

## Readiness

Este cleanup não altera versão, provider de produção, RuntimeDefinition, processo de instância ou schema de banco. É uma reorganização de fixtures + documentação + guarda arquitetural. Portanto não exige patch release isolada; deve seguir no próximo pacote normal depois de CI/merge.
