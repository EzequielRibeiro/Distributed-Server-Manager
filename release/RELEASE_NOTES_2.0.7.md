# Capivara DSM 2.0.7

Esta release consolida as mudanças integradas após a v2.0.6, com foco em operação distribuída, isolamento de responsabilidades entre Controller e Agent, administração, persistência e experiência do cliente.

## Destaques

- Customer Geographic Placement: o cliente escolhe apenas a Region/localização lógica; Agent, Node, Datacenter, hosts e fingerprints permanecem internos ao Controller.
- Storage Pools: placement por capacidade, telemetria e migração de instâncias entre pools.
- Provisionamento distribuído: Controller mantém orquestração/persistência e o Agent é responsável pela materialização do runtime.
- Agent Linux e Windows: expansão de paridade, runtime, console, arquivos, telemetria, doctor, relink e operações distribuídas.
- Activity Audit semântico persistido em banco para ações humanas.
- Universal Events append-only, ciclo de vida de Alerts em banco e notification outbox persistente.
- Remoção de filas, workers, timers e estados duráveis antigos baseados em arquivos.
- Reconciliação de unidades systemd aposentadas durante reinstalação/upgrade.
- Administração de clientes, usuários, contratos, perfis e workspace de instâncias ampliada.
- Baseline PostgreSQL v2 e reforço das fronteiras de persistência entre bancos suportados.
- Mais testes end-to-end e regressões, incluindo Customer Workspace, Placement, Agent Runtime e Phase 22.

## Segurança e privacidade de topologia

As respostas destinadas ao cliente não expõem `agent_id`, `node_id`, `datacenter_id`, IP/host interno, fingerprint ou caminhos físicos do Controller. O Controller decide a infraestrutura real com base em elegibilidade e capacidade.

## Atualização

Use somente os artefatos oficiais publicados nesta release e valide o SHA256/manifest antes da aplicação. O pacote principal será publicado como `capivara-dsm-2.0.7.tar.gz`, acompanhado dos pacotes Agent Linux e Windows.
