# P10 — Agent Network Identity, Port Pool & Connectivity

## Objetivo

Transformar a identidade de rede e a faixa de portas do Agent em contratos explícitos, persistidos e verificáveis, consumidos de forma consistente por instalação, heartbeat, Doctor, Placement, allocator e Dashboard.

A implementação não cria uma segunda fonte de verdade: reutiliza `AgentRuntimeRepository`, `AgentPortRepository`, `LocationRepository` e `AgentPublicNetworkRepository` já existentes.

## Cronograma atualizado

Estimativa total: **7–10 dias úteis**, incluindo paridade Windows e E2E.

| Etapa | Escopo | Estimativa | Dependência |
| --- | --- | ---: | --- |
| P10.1 | Inventário de rede Linux e endereço primário | 1 dia | — |
| P10.2 | Localização/Placement e Public Host na visão do Agent | 0,5–1 dia | P10.1 |
| P10.3 | Conectividade Agent → Controller e diagnóstico sob demanda | 1–1,5 dia | P10.1 |
| P10.4 | Port Pool explícito no CLI e instalação batch/CSV | 1–1,5 dia | — |
| P10.5 | Preflight TCP/UDP e integração com allocator/Doctor | 1–1,5 dia | P10.4 |
| P10.6 | `agent-details.html`: Rede do Host, Controller e Port Pool | 1 dia | P10.1–P10.5 |
| P10.7 | Paridade Windows e migração de Agents existentes | 1–1,5 dia | P10.1–P10.6 |
| P10.8 | E2E, regressão, upgrade e homologação | 1 dia | P10.1–P10.7 |

## P10.1 — Inventário de rede do host

O heartbeat deve preservar as chaves legadas de sockets (`tcp_listen`, `udp_listen`) e acrescentar, de forma best-effort:

- hostname e FQDN;
- interface primária;
- IPv4 e IPv6 primários;
- todas as interfaces conhecidas;
- IPv4/IPv6 por interface;
- MAC address;
- estado e MTU;
- tipo de interface quando disponível;
- gateway padrão IPv4/IPv6;
- rota padrão e IP de origem;
- servidores DNS;
- marcadores de completude por coletor.

Ausência de `ip`, `ss`, rota ou DNS não deve derrubar o Agent. O inventário parcial deve ser publicado com marcadores de completude falsos.

## P10.2 — Localização e Placement

Os campos administrativos permanecem distintos da descoberta física de rede:

- Datacenter: cadastro administrativo;
- Region: derivada do Datacenter cadastrado;
- Public Host: identidade pública configurada para serviços player-facing;
- Node: identidade lógica interna.

Datacenter e Region nunca são inferidos a partir de IP local.

## P10.3 — Conectividade com o Controller

A visão administrativa deve expor:

- URL/host do Controller;
- endereço resolvido;
- porta e protocolo;
- interface e IP local usados como origem;
- DNS: sucesso/falha;
- conexão TCP: sucesso/falha;
- TLS e validade quando HTTPS;
- latência da tentativa;
- último heartbeat;
- última conexão bem-sucedida;
- falha recente/reconexões quando disponíveis.

Um teste sob demanda deve reutilizar o Doctor/Agent control plane; não deve oferecer shell arbitrário.

## P10.4/P10.5 — Port Pool e preflight

A faixa padrão continua `24000-24999`, mas deixa de ser implícita.

### Instalação individual

O CLI deve exibir e permitir configurar a faixa antes do enrollment/ativação.

### Instalação em lote

O CSV deve aceitar faixa por Agent. Agents em hosts diferentes podem compartilhar a mesma faixa sem conflito entre si.

### Preflight

Antes da ativação:

1. validar limites e tamanho da faixa;
2. coletar sockets TCP/UDP locais;
3. comparar com reservas persistidas;
4. classificar conflitos externos;
5. impedir configuração inválida ou capacidade operacional insuficiente;
6. persistir a faixa aprovada.

Portas isoladas já ocupadas não invalidam automaticamente todo o Agent; devem ser excluídas da capacidade efetiva. Falhas de coleta que impeçam uma decisão segura são tratadas como erro de preflight.

## P10.6 — Agent Details

A página deve apresentar três blocos distintos:

1. **Identidade / Rede do Host** — IP principal e inventário de interfaces;
2. **Conectividade com o Controller** — rota, DNS, TCP/TLS, latência e heartbeat;
3. **Localização e Placement** — Datacenter, Region, Public Host e Node.

A seção de portas deve mostrar faixa, capacidade, reservas, conflitos externos, disponíveis e última validação.

## P10.7 — Compatibilidade

Agents existentes sem Port Pool explicitamente configurado devem ser migrados para a faixa que já utilizam, preservando `24000-24999` quando esse for o estado legado. Não deve ser exigida reinstalação.

Linux e Windows devem publicar o mesmo contrato de negócio, ainda que usem coletores nativos diferentes.

## Critérios de conclusão

- `Endereço` mostra o endereço primário reportado quando não há `advertise_address` explícito;
- múltiplas interfaces são visíveis no inventário;
- Location/Placement usa as fontes administrativas existentes;
- conectividade com o Controller é mensurável e diagnosticável;
- CLI individual e CSV tornam a faixa explícita;
- preflight TCP/UDP é executado antes da ativação;
- allocator nunca seleciona uma porta reservada ou em conflito externo;
- Doctor consegue detectar conflito surgido após instalação;
- Agents existentes continuam operando sem reinstalação;
- Linux e Windows possuem paridade de contrato;
- E2E cobre instalação individual, batch, restart, upgrade e provisionamento real.
