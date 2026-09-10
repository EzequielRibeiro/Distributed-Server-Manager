# Adaptadores de jogos do Capivara

O diretório `games/` é o namespace de **adaptadores operacionais** do Capivara. Ele não é um catálogo de jogos.

A fonte única de verdade para descoberta, versões, builds, providers, requisitos, plataformas e preparação de instalações é `catalog/v2/games/<game>/runtimes/`, junto das respectivas `GameDefinition` em `catalog/v2/games/<game>/game.json`.

## Contrato do Game Adapter

Um diretório `games/<game>/` existe somente quando o caminho operacional/compatível em shell precisa de comportamento específico do jogo. O loader legado/compatível `core/game_loader.sh` resolve adaptadores nesse namespace e o caminho local `server/start.sh` pode carregar `games/<game>/runtime.sh`.

Arquivos do adaptador podem incluir:

- `runtime.sh`: contrato operacional do jogo para o caminho shell/local; obrigatório quando o adaptador é consumido por `core/game_loader.sh`;
- `launcher.sh`: construção/execução controlada do processo;
- `process.sh`: identificação e inspeção do processo;
- `validate.sh`: validações específicas do runtime;
- `game.conf`: defaults necessários ao adaptador em tempo de execução.

`game.conf` pode manter campos históricos de instalação apenas enquanto forem necessários à compatibilidade, mas esses campos **não são autoridade de catálogo**, não participam da descoberta e não devem ser usados para escolher provider, versão ou build em fluxos Catalog v2.

Jogos simples devem preferir os Runtime Profiles permitidos pelo Catalog v2, como `catalog-native`. Um novo diretório em `games/` só deve ser criado quando existir necessidade operacional específica ou compatibilidade comprovada.

Fixtures e falsos jogos usados para testar providers não pertencem a este namespace. Use `tests/fixtures/game-adapters/`.

Nenhum manifest de catálogo pode introduzir shell arbitrário para ser `source`/executado como adaptador.
