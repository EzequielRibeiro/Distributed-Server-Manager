# Inventário inicial dos diretórios relacionados a jogos

Este documento registra o levantamento da reorganização iniciada em `refactor/game-directory-layout`.

Objetivo: identificar o que hoje pertence ao catálogo declarativo, ao adaptador operacional de cada jogo, ao conteúdo instalável, a testes de providers e a material legado antes de mover qualquer caminho consumido pelo Capivara DSM.

## Classificações usadas

- **CANÔNICO** — fonte de verdade que deve permanecer ou tornar-se a referência oficial.
- **ESPECÍFICO DO JOGO** — comportamento operacional pertencente ao adaptador do jogo.
- **REUTILIZÁVEL** — lógica comum, independente de jogo, que deve continuar fora de um diretório específico.
- **DUPLICADO** — informação representada em mais de um local e que exige consolidação.
- **LEGADO** — estrutura mantida apenas por compatibilidade ou que deverá ser removida após migração.
- **TESTE** — fixture ou adaptador criado exclusivamente para validar providers/comportamentos.

## 1. Catálogo declarativo atual

### `catalog/v2/runtimes/`

O catálogo possui manifests agrupados por jogo para:

- `arma3/`
- `dayz/`
- `luanti/`
- `mindustry/`
- `minecraft/`
- `rust/`

Classificação atual: **CANÔNICO**, porém com caminho transitório.

Destino arquitetural previsto:

```text
catalog/v2/games/<game>/runtimes/
```

Nenhum manifest deve ser movido antes da camada de compatibilidade de lookup estar pronta.

### `catalog/v2/content/`

No levantamento inicial, existe conteúdo declarativo por jogo em:

- `minecraft/`

Classificação atual: **CANÔNICO**, caminho transitório.

Destino arquitetural previsto:

```text
catalog/v2/games/<game>/content/
```

O fato de apenas Minecraft possuir conteúdo catalogado neste diretório não significa que outros jogos não suportem conteúdo; significa somente que o catálogo v2 ainda não possui manifests equivalentes para eles.

## 2. Adaptadores operacionais atuais em `games/`

O diretório `games/` mistura adaptadores de jogos reais e fixtures de teste de providers. Esta mistura é uma das principais razões para a reorganização.

### Jogos reais identificados

- `games/arma3/`
- `games/dayz/`
- `games/luanti/`
- `games/mindustry/`
- `games/minecraft/`
- `games/minecraft-java/`
- `games/rust/`

Classificação geral: **ESPECÍFICO DO JOGO**, com necessidade de auditoria arquivo a arquivo.

### Fixtures/ambientes de teste identificados

- `games/custom-provider-test/`
- `games/github-provider-test/`
- `games/http-fail-test/`
- `games/http-provider-test/`
- `games/local-provider-test/`

Classificação: **TESTE**.

Direção recomendada: retirar estes diretórios do namespace `games/` em etapa posterior e movê-los para uma área de fixtures/testes, por exemplo:

```text
tests/fixtures/providers/
```

Essa mudança não deve ocorrer antes de localizar todas as referências dos testes atuais.

## 3. DayZ — primeiro inventário detalhado

Arquivos encontrados em `games/dayz/`:

| Arquivo | Classificação inicial | Observação |
| --- | --- | --- |
| `game.conf` | DUPLICADO / LEGADO | Contém parâmetros do adaptador, mas parte das definições instaláveis já pertence ao catálogo v2. Deve ser reduzido ao que é estritamente operacional. |
| `installer.sh` | ESPECÍFICO DO JOGO / candidato a LEGADO | Deve ser comparado com o pipeline genérico do catálogo e providers. Instalação de artefato não deve continuar duplicada no adaptador se o catálogo já a resolve. |
| `launcher.sh` | ESPECÍFICO DO JOGO | Mantém valor como adaptador de execução. |
| `process.sh` | ESPECÍFICO DO JOGO | Operação/processo. |
| `runtime-native.sh` | ESPECÍFICO DO JOGO | Adaptador operacional; verificar sobreposição com `runtime.sh`. |
| `runtime.sh` | ESPECÍFICO DO JOGO | Runtime operacional do jogo. |
| `validate.sh` | ESPECÍFICO DO JOGO / REUTILIZÁVEL parcial | Regras próprias do DayZ ficam aqui; validações genéricas devem migrar para serviços compartilhados. |

### Risco principal no DayZ

`installer.sh` e `game.conf` são os primeiros candidatos a conter responsabilidade que hoje também existe em `catalog/v2/runtimes/dayz/` e nos providers genéricos.

Antes de removê-los ou reduzi-los, deve ser feito um diff semântico entre:

```text
games/dayz/game.conf
games/dayz/installer.sh
catalog/v2/runtimes/dayz/*
catalog/v2/providers/*
```

## 4. Minecraft — inventário inicial

Arquivos encontrados em `games/minecraft/`:

| Arquivo | Classificação inicial |
| --- | --- |
| `game.conf` | DUPLICADO / LEGADO parcial |
| `launcher.sh` | ESPECÍFICO DO JOGO |
| `process.sh` | ESPECÍFICO DO JOGO |
| `runtime.sh` | ESPECÍFICO DO JOGO |

Existe ainda `games/minecraft-java/`, que precisa ser comparado com `games/minecraft/` antes de qualquer consolidação. A coexistência dos dois nomes é um sinal explícito de possível sobreposição histórica.

Minecraft também é atualmente o único jogo com árvore em `catalog/v2/content/`, portanto será útil como segundo piloto depois do DayZ para validar a união entre runtime e conteúdo no novo namespace.

## 5. Rust — inventário inicial

Arquivos encontrados em `games/rust/`:

| Arquivo | Classificação inicial |
| --- | --- |
| `game.conf` | DUPLICADO / LEGADO parcial |
| `launcher.sh` | ESPECÍFICO DO JOGO |
| `process.sh` | ESPECÍFICO DO JOGO |
| `runtime.sh` | ESPECÍFICO DO JOGO |

A mesma regra aplicada a DayZ/Minecraft vale aqui: definições de instalação, versão e provider devem permanecer no catálogo; o diretório `games/rust/` deve convergir para operação do processo.

## 6. Estrutura alvo por responsabilidade

```text
catalog/v2/
├── games/
│   ├── arma3/
│   │   ├── game.json
│   │   ├── runtimes/
│   │   ├── content/
│   │   ├── network.json
│   │   └── capabilities.json
│   ├── dayz/
│   ├── luanti/
│   ├── mindustry/
│   ├── minecraft/
│   └── rust/
├── providers/
├── schemas/
└── examples/

games/
├── arma3/
├── dayz/
├── luanti/
├── mindustry/
├── minecraft/
└── rust/
```

Responsabilidades:

- `catalog/v2/games/<game>/`: metadados declarativos e instaláveis.
- `games/<game>/`: somente código/adaptadores para operar o processo.
- `catalog/v2/providers/`: providers reutilizáveis, nunca duplicados por jogo sem necessidade técnica.
- `catalog/v2/schemas/`: contratos compartilhados.
- `tests/fixtures/`: ambientes artificiais usados exclusivamente por testes.

## 7. Ordem segura de migração

1. Inventariar referências aos caminhos atuais.
2. Identificar duplicações entre `game.conf`, installers e manifests v2.
3. Criar um resolver de caminho canônico com fallback para os caminhos antigos.
4. Migrar apenas um jogo piloto.
5. Executar testes do catálogo, runtime, Dashboard e instalação.
6. Só então migrar os demais jogos.
7. Remover caminhos de compatibilidade apenas depois de uma versão de transição.

## 8. Jogo piloto recomendado

**DayZ** será o primeiro piloto porque possui a maior variedade de responsabilidades no adaptador (`installer`, `launcher`, `runtime`, `runtime-native`, `validate`) e, portanto, oferece o melhor teste para separar corretamente catálogo e operação.

O piloto não começará movendo arquivos. A próxima ação é mapear referências de código para:

```text
catalog/v2/runtimes/dayz
games/dayz/game.conf
games/dayz/installer.sh
games/dayz/runtime.sh
games/dayz/runtime-native.sh
```

Somente depois desse mapa será introduzida a camada de compatibilidade.
