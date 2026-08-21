# Adaptadores de jogos do Capivara

O diretório `games/` contém somente código e adaptadores necessários para operar processos de jogos: launcher, comandos de start/stop, integração com o Runtime operacional e configurações específicas do processo.

Ele **não é uma segunda fonte de verdade do catálogo**.

As definições declarativas instaláveis — identidade do jogo, ambientes de execução, versões, builds, requisitos, conteúdo e requisitos de rede — serão consolidadas progressivamente em `catalog/v2/games/<game>/`.

Durante a migração, os caminhos atuais em `catalog/v2/runtimes/` e `catalog/v2/content/` continuam válidos e não devem ser removidos até que todos os consumidores tenham sido migrados e os testes de compatibilidade estejam verdes.

Providers reutilizáveis permanecem em `catalog/v2/providers/` e não devem ser duplicados dentro de `games/` nem dentro de uma pasta específica de jogo.

Um `game.conf` ainda pode fornecer parâmetros ao adaptador em tempo de execução, mas não deve se tornar fonte de descoberta do catálogo quando a mesma informação já possuir representação declarativa canônica.

Consulte `docs/architecture/game-directory-layout.md` para as regras e a sequência da reorganização.
