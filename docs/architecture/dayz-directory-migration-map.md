# DayZ — mapa de migração de diretórios

Este documento registra o primeiro jogo piloto da reorganização canônica dos arquivos de jogos do Capivara DSM.

Objetivo: separar claramente **metadados declarativos**, **adaptadores operacionais** e **mecanismos reutilizáveis**, sem quebrar os caminhos atualmente consumidos pelo Runtime, instaladores, Dashboard ou testes.

## 1. Fontes atuais

### Catálogo declarativo

Arquivo atual:

```text
catalog/v2/runtimes/dayz/stable.json
```

Responsabilidades já declaradas ali:

- identidade: `id`, `name`, `game`, `edition`, `variant`;
- versão/build;
- processo: engine, executável, argumentos;
- requisitos de SO e arquitetura;
- provider de artefato, autenticação e package id;
- diretório de instalação;
- política de rede e bloco de portas;
- aplicação da porta de jogo na linha de comando.

Classificação: **CANÔNICO** para a definição instalável/runtime.

### Adaptador operacional

Diretório atual:

```text
games/dayz/
```

Arquivos encontrados:

```text
game.conf
installer.sh
launcher.sh
process.sh
runtime-native.sh
runtime.sh
validate.sh
```

## 2. Classificação inicial

| Arquivo | Classe | Decisão inicial |
|---|---|---|
| `catalog/v2/runtimes/dayz/stable.json` | CANÔNICO | manter como fonte declarativa durante a transição |
| `games/dayz/game.conf` | DUPLICADO PARCIAL + ESPECÍFICO | reduzir gradualmente às propriedades exclusivamente operacionais |
| `games/dayz/installer.sh` | ESPECÍFICO, porém fino | manter temporariamente; ele apenas delega ao Installation Manager |
| `games/dayz/launcher.sh` | ESPECÍFICO DO JOGO | manter como adaptador operacional |
| `games/dayz/process.sh` | ESPECÍFICO DO JOGO | manter como adaptador operacional |
| `games/dayz/runtime.sh` | ESPECÍFICO DO JOGO | manter até comparação funcional completa |
| `games/dayz/runtime-native.sh` | POSSÍVEL DUPLICADO | comparar com `runtime.sh` antes de consolidar |
| `games/dayz/validate.sh` | ESPECÍFICO DO JOGO | manter; revisar o que pode migrar para validação genérica |

## 3. Duplicação confirmada em `game.conf`

`games/dayz/game.conf` repete hoje informações já presentes em `stable.json`, incluindo:

- `GAME_ID=dayz`;
- nome do jogo;
- arquitetura `x86_64`;
- provider `steam`;
- package/app id `223350`;
- autenticação `required`;
- diretório `/opt/dsm/game-data/dayz/serverfiles`;
- executável `DayZServer`;
- variante `stable`;
- versão `current`;
- engine `native`.

Esses valores não devem continuar sendo mantidos em duas fontes independentes.

## 4. Informações ainda exclusivas do adaptador

No estado atual, `game.conf` também contém propriedades que não aparecem no runtime manifest e não devem ser apagadas sem substituição explícita:

- `GAME_DEFINITION_VERSION`;
- `GAME_DEFINITION_TYPE`;
- `GAME_SUPPORT_STATUS`;
- `GAME_CATEGORY`;
- `APPID_WORKSHOP=221100`;
- `LOG_EXTENSION=.RPT`;
- `MOD_PREFIX=@`.

Na reorganização futura, essas propriedades devem ser classificadas entre:

```text
catalog/v2/games/dayz/game.json
catalog/v2/games/dayz/capabilities.json
catalog/v2/games/dayz/content/
```

ou permanecer no adaptador quando forem estritamente ligadas ao processo local.

## 5. Installer

`games/dayz/installer.sh` não implementa SteamCMD, rollback, swap atômico ou verificação de integridade. Ele apenas delega para:

```text
installer/manager.sh
```

por meio de chamadas como:

```text
install_manager_install dayz
install_manager_update dayz
install_manager_validate dayz
install_manager_rollback dayz
install_manager_info dayz
```

Portanto ele não é uma segunda implementação do provider Steam. Antes de removê-lo, é necessário verificar se há chamadas externas às funções `dayz_*`.

## 6. Estrutura alvo para o piloto

A estrutura canônica pretendida para os dados declarativos do DayZ é:

```text
catalog/v2/games/dayz/
├── game.json
├── runtimes/
│   └── stable.json
├── content/
├── network.json
└── capabilities.json
```

Nem todos os arquivos precisam ser criados imediatamente. A migração deve ocorrer apenas quando houver um consumidor compatível.

O código operacional continuará separado:

```text
games/dayz/
├── launcher.sh
├── process.sh
├── runtime.sh
└── validate.sh
```

Arquivos adicionais permanecem até que sua redundância seja comprovada.

## 7. Regra de compatibilidade

Nenhum caminho atual deve ser removido na primeira migração física.

A ordem obrigatória será:

1. introduzir leitura no novo namespace;
2. manter fallback para `catalog/v2/runtimes/dayz/stable.json`;
3. validar catálogo, instalação, start/stop e Dashboard;
4. migrar o manifest;
5. executar CI/testes;
6. somente depois remover o caminho antigo em uma etapa separada.

## 8. Próximo passo

Antes da primeira movimentação física:

- mapear consumidores de `catalog/v2/runtimes/<game>`;
- mapear consumidores de `games/<game>/game.conf`;
- mapear chamadas das funções exportadas por `games/dayz/installer.sh`;
- comparar `runtime.sh` com `runtime-native.sh`;
- identificar testes que codificam os caminhos atuais.

Somente após esse inventário a branch deverá introduzir uma camada de resolução de caminhos canônicos/legados.
