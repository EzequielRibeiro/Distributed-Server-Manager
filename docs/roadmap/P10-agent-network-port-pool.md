# P10 — Agent Network Identity, Port Pool & Connectivity

## Objetivo

Transformar a identidade de rede e a faixa de portas do Agent em contratos explícitos, persistidos e verificáveis, consumidos de forma consistente por instalação, heartbeat, Doctor, Placement, allocator e Dashboard.

A implementação não cria uma segunda fonte de verdade: reutiliza `AgentRuntimeRepository`, `AgentPortRepository`, `LocationRepository` e `AgentPublicNetworkRepository` já existentes.

## Estado da implementação

| Etapa | Escopo | Estado |
| --- | --- | --- |
| P10.1 | Inventário de rede Linux e endereço primário | implementado |
| P10.2 | Localização/Placement e Public Host na visão do Agent | implementado |
| P10.3 | Conectividade Agent → Controller e diagnóstico sob demanda | integrado e coberto por gate |
| P10.4 | Port Pool explícito no CLI e instalação batch/CSV | implementado |
| P10.5 | Preflight TCP/UDP e integração com allocator/Doctor | implementado como readiness antes do provisioning |
| P10.6 | `agent-details.html`: Rede do Host, Controller e Port Pool | implementado |
| P10.7 | Paridade Windows e migração de Agents existentes | implementado no contrato de heartbeat; sem reinstalação |
| P10.8 | E2E, regressão, upgrade e homologação | gate dedicado criado; homologação runtime depende de deploy do código aprovado |

## P10.1 — Inventário de rede do host

O heartbeat preserva as chaves de sockets (`tcp_listen`, `udp_listen`) e acrescenta, de forma best-effort:

- hostname e FQDN;
- interface primária;
- IPv4 e IPv6 primários;
- todas as interfaces conhecidas;
- IPv4/IPv6 por interface;
- MAC address;
- estado e MTU;
- gateway padrão IPv4/IPv6;
- rota padrão e IP de origem no Linux;
- servidores DNS;
- marcadores de completude por coletor.

Ausência de um coletor não derruba o Agent. O inventário parcial é publicado com marcadores de completude falsos.

## P10.2 — Localização e Placement

Os campos administrativos permanecem distintos da descoberta física de rede:

- Datacenter: cadastro administrativo;
- Region: derivada do Datacenter cadastrado;
- Public Host: identidade pública configurada para serviços player-facing;
- Node: identidade lógica interna.

Datacenter e Region nunca são inferidos a partir de IP local.

## P10.3 — Conectividade com o Controller

O comando existente `cap agent controller test [URL] --json` é o contrato de diagnóstico sob demanda e foi incorporado ao gate P10. Ele valida:

- resolução DNS;
- conexão TCP;
- TLS quando HTTPS;
- endpoint HTTP `/ping`;
- latência;
- certificado e validade quando aplicável.

A visão administrativa usa heartbeat/health para representar a conectividade contínua com o Controller atual. O teste aprofundado permanece no Agent e não oferece shell remoto arbitrário.

## P10.4 — Port Pool e instalação batch

A faixa deixa de depender de convenção implícita. A instalação individual já recebe `--port-range START-END` e `--port-protocol tcp|udp|both`.

Foi acrescentado:

```text
cap agent deploy-batch FILE.csv [--continue-on-error] [--json]
```

O CSV aceita por Agent: host, usuário SSH, plataforma, credencial por arquivo, Controller, Region, Datacenter, nome, faixa/protocolo de portas, origem do pacote e timeouts. Senha em texto puro não é uma coluna válida.

O batch chama o pipeline normal de `agent_deploy_cli.deploy()` para cada linha; não existe um segundo mecanismo de enrollment.

## P10.5 — Preflight TCP/UDP

O preflight operacional ocorre depois do primeiro heartbeat e **antes de o Agent ser considerado elegível para provisioning/allocator**. Esse ponto é deliberado: a fonte autoritativa de sockets do host é o próprio Agent instalado, não uma inspeção paralela via bootstrap SSH.

O contrato `port_pool_preflight()` cruza:

1. faixas persistidas;
2. reservas de instâncias;
3. sockets TCP/UDP observados pelo heartbeat;
4. maior bloco contíguo disponível;
5. conflitos externos;
6. completude do inventário de rede.

Uma porta isolada ocupada reduz a capacidade efetiva sem invalidar o Agent inteiro. Inventário incompleto é sinalizado explicitamente. O allocator continua consumindo as reservas persistidas e a disponibilidade efetiva existente.

## P10.6 — Agent Details

`agent-details.html` carrega um módulo independente de rede que mostra:

- interface principal;
- IPv4/IPv6;
- gateways;
- DNS;
- interfaces, MAC, MTU e estado;
- completude do inventário;
- heartbeat com o Controller;
- preflight TCP e UDP e maior bloco contíguo disponível.

Localização/Placement continua em bloco distinto.

## P10.7 — Compatibilidade e Windows

Não há migração de schema. Agents existentes continuam válidos e, após receberem o runtime atualizado, passam a enriquecer o mesmo `network_json` já persistido. Não é necessária reinstalação.

Linux usa coletores `ip`, `/sys`, `ss` e resolvers locais. Windows usa `Get-NetIPConfiguration`, `Get-NetRoute` e `netstat`, mas publica o mesmo contrato de negócio.

Port Pools já persistidos são preservados. O legado `24000-24999` continua compatível quando já configurado; novas instalações devem declará-lo explicitamente ou escolher outra faixa.

## P10.8 — Validação

O workflow `P10 Agent Network and Port Pool` executa syntax gates e testes para:

- inventário Linux;
- inventário Windows;
- endereço/Location na API;
- conectividade com Controller;
- batch CSV;
- preflight;
- UI de rede;
- roteamento público pelo `cap`.

Os workflows gerais do projeto continuam fornecendo regressão de Agent Runtime, Agent Local CLI, External Controller↔Agent E2E e CI. Homologação no host ativo é uma etapa posterior ao merge e exige rollout explicitamente autorizado.

## Critérios de conclusão

- `Endereço` usa o endereço primário reportado quando não há `advertise_address` explícito;
- múltiplas interfaces ficam disponíveis no inventário;
- Location/Placement usa as fontes administrativas existentes;
- conectividade com o Controller é mensurável e diagnosticável;
- CLI individual e CSV tornam a faixa explícita;
- preflight TCP/UDP bloqueia elegibilidade de provisioning quando não há capacidade segura;
- sockets externos são descontados da capacidade efetiva;
- Agents existentes continuam operando sem reinstalação;
- Linux e Windows possuem paridade do contrato de rede;
- CI e gates E2E passam antes do merge;
- homologação runtime/browser é comprovada somente após rollout autorizado.
