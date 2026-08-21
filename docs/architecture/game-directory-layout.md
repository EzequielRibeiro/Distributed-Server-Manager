# Organização canônica dos jogos

## Objetivo

Reduzir a dispersão de arquivos que descrevem o mesmo jogo sem quebrar os contratos atuais do catálogo, Runtime, Dashboard ou instaladores.

A reorganização será incremental. Arquivos existentes não devem ser movidos até que todas as referências de código, testes e documentação tenham sido inventariadas e uma camada de compatibilidade exista quando necessária.

## Princípio

**Tudo que descreve um jogo pertence ao domínio daquele jogo. Tudo que implementa um mecanismo reutilizável permanece compartilhado.**

Exemplos:

- identidade, capabilities, requisitos de rede e runtimes: específicos do jogo;
- Steam, HTTP archive, GitHub Releases e Modrinth: providers reutilizáveis;
- schemas: contratos compartilhados;
- adaptadores de processo: código operacional específico do jogo, mantido em `games/`.

## Estrutura alvo

```text
catalog/v2/
├── games/
│   ├── arma3/
│   ├── dayz/
│   ├── luanti/
│   ├── mindustry/
│   ├── minecraft/
│   └── rust/
├── providers/
├── schemas/
└── examples/
```

Cada diretório de jogo poderá evoluir para:

```text
catalog/v2/games/<game>/
├── game.json
├── runtimes/
├── content/
├── network.json
└── capabilities.json
```

A divisão exata será consolidada somente depois do inventário de dependências. Nem todo jogo precisa possuir todos esses arquivos.

## Responsabilidade de `games/`

O diretório de nível superior `games/` continua reservado a código/adaptadores operacionais de processo. Ele não é uma segunda fonte de verdade para descoberta do catálogo.

```text
games/<game>/
└── adaptador de execução, launcher e integração operacional
```

Metadados declarativos e itens instaláveis devem migrar progressivamente para `catalog/v2/games/<game>/`.

## Classificação usada durante a migração

Cada arquivo relacionado a jogo deve ser classificado como uma das categorias abaixo antes de ser movido:

- **CANÔNICO** — fonte de verdade declarativa do jogo;
- **ESPECÍFICO DO JOGO** — comportamento necessário apenas para um jogo;
- **REUTILIZÁVEL** — mecanismo compartilhado por vários jogos;
- **DUPLICADO** — informação já representada por outra fonte canônica;
- **LEGADO** — mantido apenas por compatibilidade e candidato à remoção futura.

## Compatibilidade durante a transição

Durante a migração, o catálogo aceita simultaneamente:

```text
# namespace canônico novo
catalog/v2/games/<game>/runtimes/<variant>.json

# namespace legado compatível
catalog/v2/runtimes/<game>/<variant>.json
```

A resolução de runtimes é centralizada em `installer/catalog_paths.sh`. O namespace novo é consultado primeiro; quando o mesmo `id` existe nos dois layouts, a definição canônica vence. As listagens eliminam duplicações por `id`.

Os comandos `runtime list`, `runtime show` e `runtime prepare` utilizam a mesma camada de resolução. Isso permite migrar os manifests jogo a jogo sem alterar os contratos públicos do Dashboard, CLI ou instalação.

Nenhum caminho legado deve ser removido antes de:

1. localizar referências aos caminhos atuais;
2. adicionar testes de contrato para a nova organização;
3. validar fallback e precedência do loader compatível;
4. migrar um jogo piloto;
5. validar CI e regressões;
6. somente então migrar os demais jogos.

## Ordem proposta

### Etapa A — estrutura e inventário

- criar `catalog/v2/games/`;
- documentar responsabilidades;
- inventariar arquivos por jogo;
- identificar duplicações e caminhos consumidos pelo código.

### Etapa A.3 — resolução compatível de caminhos

- adicionar `installer/catalog_paths.sh`;
- procurar primeiro `catalog/v2/games/<game>/runtimes/`;
- fazer fallback para `catalog/v2/runtimes/<game>/`;
- deduplicar listagens por `id`, preservando a definição canônica;
- usar a mesma resolução em `runtime list`, `runtime show` e `runtime prepare`;
- testar os cenários legacy-only, canonical-only, coexistência e precedência.

### Etapa B — registro canônico

- introduzir identidade canônica por jogo;
- disponibilizar listagem de jogos sem deduzi-la apenas dos runtimes;
- preparar endpoint conceitual `/api/catalog/games`.

### Etapa C — migração piloto

- usar DayZ como primeiro jogo piloto;
- mover o manifesto somente após aprovação dos testes da camada de compatibilidade;
- manter compatibilidade com os caminhos antigos durante a transição;
- validar Dashboard, CLI e instalação.

### Etapa D — migração dos demais jogos

- migrar jogo a jogo;
- remover duplicações comprovadas;
- atualizar testes e documentação.

### Etapa E — retirada do legado

- remover loaders e caminhos antigos apenas quando não houver consumidores restantes;
- manter providers compartilhados fora das pastas de jogos.

## Regra para novos jogos

Enquanto a migração estiver em andamento, novos jogos não devem introduzir mais uma estrutura paralela. A identidade declarativa deverá seguir a organização definida em `catalog/v2/games/`, e mecanismos genéricos devem ser reutilizados em vez de copiados para cada jogo.
