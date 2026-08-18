# Capivara DSM - Management Surface v1.20

## Escopo

A Management Surface unifica:

- arquivos de configuraÃ§Ã£o reais das instÃ¢ncias;
- configuraÃ§Ã£o de mods e plugins;
- parÃ¢metros estruturados de inicializaÃ§Ã£o;
- estado e saÃºde das portas;
- inventÃ¡rio de rede dos Agents;
- configuraÃ§Ã£o do catÃ¡logo;
- topologia de regiÃµes e datacenters;
- preferÃªncia regional do cliente;
- fundamentos de placement por regiÃ£o, latÃªncia e carga.

## ConfiguraÃ§Ã£o da instÃ¢ncia

A Ã¡rea ConfiguraÃ§Ãµes deve apresentar arquivos declarados
pelo runtime e arquivos de configuraÃ§Ã£o descobertos na
instalaÃ§Ã£o real do jogo.

Arquivos internos do Capivara, como `server.conf`, nÃ£o
representam a configuraÃ§Ã£o do jogo e nÃ£o devem substituir
arquivos como `serverDZ.cfg`, `server.properties` ou
equivalentes.

## CatÃ¡logo

ConfiguraÃ§Ãµes pertencentes ao catÃ¡logo podem ser
visualizadas por usuÃ¡rios autorizados.

Somente usuÃ¡rios com papel `admin` podem editar conteÃºdo
do catÃ¡logo nesta versÃ£o.

## Rede

Portas de jogo, query, RCON e demais endpoints sÃ£o
modeladas pelo perfil de rede do runtime.

Cliente, Controller e Admin podem receber informaÃ§Ãµes
compatÃ­veis com seu escopo e permissÃµes.

## Placement geogrÃ¡fico

O cliente pode indicar preferÃªncia por uma regiÃ£o.

A preferÃªncia nÃ£o equivale a escolher diretamente um
Agent fÃ­sico. A decisÃ£o final pertence Ã  polÃ­tica de
placement do Controller.

A polÃ­tica pode combinar:

1. regiÃ£o preferencial;
2. restriÃ§Ã£o ou autorizaÃ§Ã£o de cross-region;
3. latÃªncia conhecida;
4. distÃ¢ncia geogrÃ¡fica como fallback;
5. carga atual do Agent.

Isso evita, por exemplo, colocar automaticamente uma
instÃ¢ncia de um cliente no Brasil em um datacenter distante
quando existe uma regiÃ£o elegÃ­vel mais adequada.

## SeguranÃ§a

A implementaÃ§Ã£o mantÃ©m lÃ³gica especializada fora de
`dashboard/server.py`. O arquivo principal permanece
responsÃ¡vel principalmente por composiÃ§Ã£o e roteamento HTTP.
