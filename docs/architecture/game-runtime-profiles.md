# B9 — Game Runtime Profiles

## Objetivo

Game Runtime Profiles formam a fronteira entre dados específicos de um jogo e o runtime genérico introduzido em B6–B8. Um profile conhece o contrato de inicialização do jogo; `RuntimeSpec`, materializers e adapters continuam sem conhecimento de jogo.

```text
Instance + installed content + reserved ports + configuration
                         │
                         ▼
                 GameRuntimeProfile
                         │
                         ▼
          CapivaraInstanceRuntimeSpec
                         │
                         ▼
                B8 Materializer
                         │
                         ▼
                 Runtime Adapter
```

## Contrato

Todos os profiles implementam `GameRuntimeProfile.build_runtime_spec(instance, context)`. O resultado passa obrigatoriamente por `validate_runtime_spec` antes da materialização.

O registry é explícito e allowlisted. `environment_id` tem precedência sobre `game_id`, permitindo versões/canais futuros sem espalhar condicionais pelo runtime.

## Responsabilidades

Um profile pode:

- resolver executável dentro do conteúdo já instalado;
- selecionar diretório de trabalho;
- traduzir portas previamente reservadas em argumentos ou environment;
- referenciar arquivos de configuração já provisionados;
- produzir argumentos estruturados do jogo;
- adicionar environment específico do jogo;
- escolher o estado desejado inicial.

Um profile não pode:

- alocar portas;
- instalar conteúdo;
- executar shell;
- escolher outro Agent;
- aceitar unit systemd enviada pelo Controller;
- modificar a policy do materializer/adapter.

## Port binding

O profile consome somente reservas recebidas no contexto. Reservas podem ser fornecidas como mapa por papel (`game`, `query`, `rcon`, etc.) ou como lista estruturada. Porta e protocolo são validados. Uma porta obrigatória ausente falha de forma explícita; nunca há fallback para uma porta inventada.

## Primeiro profile real: DayZ

`profiles/dayz.py` suporta `dayz` e `dayz.stable`.

O profile usa:

- conteúdo/working directory previamente provisionado;
- executável `DayZServer`, salvo override estruturado local;
- `serverDZ.cfg`, salvo `config_path` estruturado;
- reserva `game/udp` para `-port=<porta>`;
- argumentos extras somente como lista, sem shell;
- environment `CAPIVARA_INSTANCE_ID`, `CAPIVARA_GAME_ID` e `CAPIVARA_GAME_PORT`.

A existência do profile DayZ não altera `SystemdMaterializer`, `SystemdAdapter` nem `runtime_materialization.py`.

## Ownership

`game_runtime.build_runtime_spec` exige que `instance.agent_id` corresponda à identidade do Agent local antes de resolver qualquer profile. Depois da tradução, a RuntimeSpec é novamente validada com `expected_agent_id`.

## Eventos

Ao resolver com sucesso um profile, o Agent produz `INSTANCE_RUNTIME_PROFILE_RESOLVED` contendo apenas metadados estruturados do profile, jogo e environment. A materialização posterior continua produzindo os eventos B8.

## Extensão para novos jogos

Adicionar um novo jogo exige:

1. novo módulo em `agents/linux/runtime/profiles/`;
2. implementação de `GameRuntimeProfile`;
3. declaração explícita de `game_ids`;
4. registro em `profiles/registry.py`;
5. testes de geração de RuntimeSpec;
6. testes provando que materializer/adapter permanecem game-agnostic.

Nenhum novo jogo deve ser implementado com condicionais em `runtime_materialization.py`, `materializers/systemd.py` ou `adapters/systemd.py`.

## Limite da B9

B9 traduz uma instância já provisionada para RuntimeSpec. A orquestração completa `placement → ports → content → profile → materialization → start → rollback` pertence à B10 — Instance Provisioning Pipeline.
