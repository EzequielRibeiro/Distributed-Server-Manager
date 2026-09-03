# Project Zomboid

`projectzomboid.stable` é o runtime canônico Linux x86_64 do Project Zomboid Dedicated Server.

## Aquisição

O servidor é adquirido pelo provider Steam usando o Dedicated Server AppID `380870` com autenticação anônima.

## Primeira inicialização segura

O Project Zomboid solicita uma senha para criar a conta administrativa na primeira execução. O Agent não recebe nem persiste essa senha. O `ExecStartPre` chama um helper Capivara que:

1. verifica um marcador privado e idempotente no HOME isolado da instância;
2. gera localmente uma credencial aleatória de alta entropia;
3. inicia `start-server.sh` e envia a credencial duas vezes somente via stdin, seguida de `quit`;
4. descarta a credencial da memória e grava apenas o marcador de conclusão;
5. nunca coloca a credencial em argv, variáveis de ambiente, JSON de provisionamento, RuntimeSpec, unidade systemd ou logs.

A conta administrativa de bootstrap não é uma credencial comercial/do cliente. A administração normal permanece sob o console/RBAC do Capivara, e permissões in-game podem ser concedidas posteriormente pelo fluxo administrativo.

## Estado e configuração

O runtime usa o HOME privado montado pelo materializador systemd (`/var/lib/capivara-agent/runtime-home`, ligado ao estado privado da instância). Assim, `~/Zomboid`, saves, banco e configuração ficam fora dos arquivos Steam compartilhados e sobrevivem a atualização/reinstalação do conteúdo.

## Rede

A porta UDP principal é reservada pelo Placement e aplicada com `-port`. A alocação usa bloco de 10 portas para manter espaço adjacente para necessidades do protocolo/jogo sem colisão com outras instâncias.

## Workshop

O adapter `installer/content_adapters/project-zomboid.sh` reutiliza o provider genérico `steam-workshop` com Workshop AppID `108600`. `PublishedFileId` é materializado em `WorkshopItems` e o identificador lógico do mod em `Mods`, mantendo ordem e removendo duplicatas.
