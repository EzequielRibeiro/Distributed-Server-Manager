# Auditoria de adaptadores `games/`

Status: concluída para o cleanup arquitetural das etapas 8–13.

Base auditada: `main` em `07a66ac7e690de9db238ef2abf189cfc520c9cb4`.

## Limite arquitetural confirmado

`catalog/v2/games/` é a fonte única de verdade para descoberta e instalação: GameDefinition, RuntimeDefinition, providers, versões, builds, requisitos e plataformas.

O `games/` da raiz é um namespace operacional de adaptadores shell. Ele continua tendo consumidores reais: `core/game_loader.sh` resolve `${DSM_ROOT}/games/${GAME_ID}` e carrega `game.conf`, `process.sh` e `runtime.sh`; `server/start.sh` também resolve `games/${GAME}/runtime.sh`. Portanto, remover o diretório ou os adaptadores reais quebraria caminhos operacionais/compatíveis ainda suportados.

## Classificação

| Diretório | Classificação | Decisão |
| --- | --- | --- |
| `games/arma3` | adaptador operacional ativo | manter |
| `games/dayz` | adaptador operacional ativo | manter |
| `games/luanti` | adaptador operacional/compatibilidade | manter até migração explícita do consumidor shell |
| `games/mindustry` | adaptador operacional/compatibilidade | manter até migração explícita do consumidor shell |
| `games/minecraft` | adaptador operacional agregador (Java/Bedrock) | manter |
| `games/minecraft-java` | adaptador histórico específico Java | manter por compatibilidade; não fundir sem migração de IDs/consumidores |
| `games/rust` | adaptador operacional ativo | manter |
| `games/custom-provider-test` | fixture de provider | mover para testes |
| `games/github-provider-test` | fixture de provider | mover para testes |
| `games/http-fail-test` | fixture negativa de provider | mover para testes |
| `games/http-provider-test` | fixture de provider | mover para testes |
| `games/local-provider-test` | fixture de provider | mover para testes |

## Minecraft x Minecraft Java

Os dois adaptadores não são equivalentes no estado atual. `games/minecraft/game.conf` declara o jogo agregador `minecraft`, com edições `java bedrock`, provider dinâmico e defaults gerais. `games/minecraft-java/game.conf` declara a identidade histórica `minecraft-java`, uma versão Java fixa e contrato HTTP reproduzível. A coexistência é dívida de compatibilidade, mas a remoção/fusão sem migração poderia quebrar consumidores que ainda enviem `GAME_ID=minecraft-java`. Decisão: preservar ambos neste cleanup e registrar a futura convergência como migração separada.

## Instalação em `game.conf`

Vários adaptadores reais ainda carregam campos históricos como `INSTALL_PROVIDER`, `INSTALL_PACKAGE_ID`, `GAME_VERSION` e `GAME_BUILD`. Esses valores não podem competir com Catalog v2. O contrato foi documentado: são apenas dados de compatibilidade enquanto o caminho shell precisar deles; Catalog v2 continua sendo a autoridade de descoberta/instalação.

## Fixtures removidas do namespace de produção

Os cinco falsos jogos de provider foram preservados em `tests/fixtures/game-adapters/<fixture>/game.conf` e removidos de `games/`. Isso evita que scans/consumidores do namespace operacional confundam testes com jogos reais sem perder material de regressão.

## Dívidas identificadas, não removidas neste cleanup

- `server/process.sh` contém lógica DayZ em uma superfície genericamente nomeada; mover/remover exige auditoria própria de consumidores.
- `minecraft-java` pode ser convergido ao modelo hierárquico `minecraft`, mas somente com migração explícita de compatibilidade.
- campos de instalação em `game.conf` devem desaparecer gradualmente à medida que os consumidores shell forem migrados para RuntimeDefinition/Runtime Profile.
- adaptadores `luanti` e `mindustry` podem futuramente tornar-se dispensáveis se todos os seus consumidores forem comprovadamente `catalog-native`/typed profiles; isso não está provado para o caminho shell atual.

## Guardas adicionados

`tests/game_adapter_architecture_test.py` impede o retorno dos cinco provider fixtures para `games/`, garante o contrato `runtime.sh` dos adaptadores operacionais conhecidos e valida que a documentação aponta para `catalog/v2/games/<game>/runtimes/`.

## Readiness

Este cleanup não altera versão, provider, RuntimeDefinition, processo de instância ou schema de banco. É uma reorganização de fixtures + documentação + guarda arquitetural. Portanto não exige patch release isolada; deve seguir no próximo pacote normal depois de CI/merge.
