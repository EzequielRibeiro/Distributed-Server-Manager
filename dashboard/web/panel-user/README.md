# Capivara DSM — Painel de servidores de jogos

Protótipo navegável da interface cliente do Capivara-DSM, inspirado nas referências fornecidas e adaptado para uma plataforma multi-jogo.

## Decisão de produto

O painel compartilha navegação, métricas, console, arquivos, backups e ciclo de vida entre todos os jogos. Configurações e fluxos de importação são fornecidos por adaptadores específicos:

- Minecraft: mundo, modo de jogo, dificuldade, whitelist, propriedades, Paper/Fabric/Forge;
- Rust: mapa, seed, wipe, Oxide/uMod, `server.cfg`;
- DayZ: missão, economia, perfis, Workshop e `serverDZ.cfg`;
- Arma 3: missão, DLCs, mods, parâmetros e `server.cfg`.

## Importação local

O protótipo aceita seleção de pasta com a API de arquivos do navegador e simula a análise. Na integração real, os arquivos devem ser enviados por partes para o backend, armazenados em área temporária e validados antes da extração. O backend deve impedir path traversal, links simbólicos perigosos, executáveis inesperados, colisões de porta e sobrescrita sem confirmação.

## Executar

Abra `index.html` no navegador ou sirva a pasta com qualquer servidor HTTP estático.

## Integração sugerida

1. `POST /api/imports` cria a sessão de upload.
2. `PUT /api/imports/:id/chunks/:part` recebe arquivos em partes.
3. `POST /api/imports/:id/analyze` detecta jogo/perfil e produz relatório.
4. `POST /api/imports/:id/commit` instala após confirmação.
5. Adaptadores implementam `detect`, `validate`, `normalizeConfig`, `startCommand` e `healthProbe`.
