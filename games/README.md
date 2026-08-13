# Adaptadores de jogos do Capivara

O diretório `games/` contém somente adaptadores necessários para operar processos de jogos: launcher, comandos de start/stop, integração com o Runtime operacional e configurações específicas do processo.

As definições instaláveis, providers, versões, builds, requisitos e destinos pertencem exclusivamente ao catálogo em `catalog/v2/runtimes/`.

Um `game.conf` ainda pode fornecer parâmetros ao adaptador em tempo de execução, mas não participa da descoberta nem da preparação de instalações do catálogo.
