# Capivara Distributed Server Manager

<div align="center">

**Plataforma distribuída para implantação, operação e monitoramento de servidores de jogos em múltiplos hosts e datacenters.**

![CI](https://github.com/EzequielRibeiro/Distributed-Server-Manager/actions/workflows/ci.yml/badge.svg)
![Linux](https://img.shields.io/badge/Controller-Linux-2ea44f)
![Agent Linux](https://img.shields.io/badge/Agent-Linux-2ea44f)
![Agent Windows](https://img.shields.io/badge/Agent-Windows-0078d4)
![Python](https://img.shields.io/badge/Python-3.x-yellow)

</div>

---

## Sobre o projeto

O **Capivara DSM (Distributed Server Manager)** é um gerenciador distribuído de servidores de jogos.

O projeto começou como um gerenciador dedicado ao DayZ e evoluiu para uma arquitetura **multi-game, multi-host e multi-datacenter**, com separação entre **Controller**, **Agents** e instâncias de jogos.

O Controller mantém a visão administrativa e coordena a infraestrutura. Os Agents executam as operações nos hosts responsáveis pelas instâncias. O modo **Híbrido** permite que a mesma máquina atue como Controller e Agent.

```text
Cliente / Administrador
        │
        ▼
     Controller
        │
        ├── Region
        │    └── Datacenter
        │         └── Agent
        │              └── Instâncias de jogos
        │
        └── Clientes / Contratos / Alertas / Eventos
```

---

## Estado atual

O Capivara DSM já possui uma base funcional para gerenciamento distribuído, incluindo:

- Controller, Agent e modo Híbrido;
- Agents Linux e Windows;
- enrollment, pairing seguro e heartbeat de Agents;
- localização de Agents por região e datacenter;
- verificação de elegibilidade e readiness para placement;
- criação e gerenciamento de instâncias;
- reservas e administração de portas por Agent;
- runtime multi-game;
- catálogo de jogos e providers;
- instalação e gerenciamento via SteamCMD quando aplicável;
- monitoramento de CPU, memória, disco e estado operacional;
- eventos, alertas e auditoria;
- backups e scheduler;
- RBAC para administrador, controller e cliente;
- painel separado para clientes;
- instalação remota de Agents Linux via SSH;
- atualização remota e rollout de Agents;
- Update Manager com validação de releases;
- Dashboard Web v2.

---

## Dashboard Web v2

A interface atual foi reorganizada para uma operação mais próxima de painéis modernos de hospedagem de jogos.

### Visão Geral

- resumo operacional da instância ativa;
- CPU, RAM e disco;
- status do servidor;
- console/logs em destaque;
- ações de iniciar, reiniciar e parar;
- informações de Runtime e saúde operacional.

### Servidores

A página de servidores apresenta uma visão consolidada das instâncias publicadas pelo Runtime:

- status Online / Offline / Atenção;
- jogo e nome da instância;
- jogadores;
- CPU e RAM;
- Agent responsável;
- localização;
- filtros e pesquisa;
- atalhos para Console e gerenciamento.

### Infraestrutura

A área de infraestrutura centraliza:

- Agents;
- instalação de novos Agents;
- instalação remota via SSH;
- atualização e rollout;
- faixas de portas;
- localização;
- topologia visual.

A topologia segue os dados reais fornecidos pelo Controller:

```text
Controller
   └── Region
        └── Datacenter
             └── Agent
                  └── Instâncias
```

Agents sem localização configurada também são identificados pela interface.

---

## Arquitetura

### Controller

Responsável por:

- autenticação e RBAC;
- clientes e contratos;
- visão global dos Agents;
- topologia;
- placement;
- coordenação de criação de instâncias;
- alertas, eventos e auditoria;
- Dashboard Web;
- distribuição de operações para os Agents.

### Agent

Responsável pelo host onde as cargas realmente executam:

- instalação e operação dos servidores de jogos;
- runtime local;
- métricas e inventário;
- portas e disponibilidade de rede;
- SteamCMD quando necessário;
- atualização do próprio Agent;
- comunicação autenticada com o Controller.

### Híbrido

Executa Controller e Agent na mesma máquina, mantendo os mesmos contratos de comunicação e placement utilizados por Agents remotos.

---

## Topologia e placement

O Capivara DSM não considera a simples existência de um Agent como suficiente para receber uma instância.

O placement depende da validade da infraestrutura e do estado operacional disponível, considerando conceitos como:

```text
Controller válido
+
Region válida
+
Datacenter válido
+
Agent elegível/ativo
+
Localização e requisitos do jogo
=
Agent candidato ao placement
```

A implementação possui diagnósticos específicos para readiness, indisponibilidade e requisitos de placement.

---

## Banco de dados

O Controller utiliza uma camada de persistência para informações administrativas e operacionais, incluindo entidades como:

- controllers;
- agents;
- customers;
- contracts;
- instances;
- instance ports;
- regions;
- datacenters;
- alerts;
- events;
- audit log;
- usuários do Dashboard.

A arquitetura do projeto vem sendo preparada para reduzir dependências de arquivos JSON como fonte de verdade e para permitir evolução da persistência sem acoplar a lógica de negócio diretamente ao banco.

---

## Jogos e providers

O Runtime foi desenhado para não ficar limitado ao DayZ.

Entre os fluxos já trabalhados no projeto estão:

- **DayZ** — Steam / SteamCMD;
- **Minecraft Java** — catálogo e providers, incluindo Modrinth;
- **Minecraft Bedrock** — provider de arquivo HTTP e resolver oficial;
- arquitetura extensível para novos jogos e providers.

A disponibilidade efetiva de cada operação depende do catálogo e do provider implementado para o jogo.

---

## Agents

### Linux

O Agent Linux pode ser instalado e pareado com o Controller. O Dashboard também suporta bootstrap remoto via SSH, sem receber ou armazenar senha SSH na interface.

### Windows

O projeto possui Agent Windows próprio, com runtime, capabilities, inventário de rede e mecanismo de atualização correspondente.

---

## Portas de rede

As portas são administradas por Agent.

A alocação deve considerar:

- faixa configurada para o Agent;
- reservas persistidas;
- portas realmente ocupadas no sistema operacional;
- requisitos específicos de cada jogo;
- reserva atômica para evitar colisões.

Para DayZ, a arquitetura prevê blocos de portas próprios por instância e preservação das reservas durante stop/restart.

---

## Segurança

O projeto inclui mecanismos como:

- autenticação do Dashboard;
- RBAC;
- pairing seguro de Agents;
- autenticação permanente para heartbeat;
- separação de permissões por função;
- validação de releases e atualização;
- tratamento de erros de placement sem exposição indevida de detalhes internos;
- auditoria de operações;
- isolamento progressivo entre Controller, Agent e cliente.

---

## Estrutura principal do repositório

```text
Distributed-Server-Manager/
├── agents/                 # Agents Linux e Windows
├── backup/                 # Backup e restore
├── catalog/                # Catálogo de jogos
├── core/                   # Núcleo e regras compartilhadas
├── dashboard/              # Backend e interface Web
│   └── web/                # Frontend do Dashboard
├── database/               # Persistência, migrations e repositories
├── docs/                   # Documentação arquitetural
├── games/                  # Definições e suporte aos jogos
├── release/                # Build e empacotamento
├── runtime/                # Runtime e estado operacional
├── systemd/                # Serviços Linux
├── tests/                  # Testes e gates de regressão
├── bin/                    # CLI
└── install.sh              # Instalador
```

---

## Instalação

O instalador oferece três papéis:

```text
Controller
Agent
Híbrido
```

Cada papel instala apenas os componentes necessários para sua responsabilidade.

> O projeto ainda está em desenvolvimento ativo. Antes de utilizar em produção, revise a versão/release, documentação e requisitos correspondentes ao ambiente desejado.

---

## Desenvolvimento e qualidade

O repositório possui CI automatizado com validações de:

- sintaxe Bash;
- PowerShell;
- JSON;
- Python;
- JavaScript do Dashboard;
- installer;
- updater;
- CLI e scheduler;
- catálogo;
- build de release;
- pacotes dos Agents Linux e Windows;
- testes de placement, infraestrutura e RBAC;
- regressões e cenários end-to-end.

O desenvolvimento prioriza modularização. Novas responsabilidades devem ser implementadas em módulos específicos em vez de aumentar arquivos centrais já extensos.

---

## Roadmap resumido

Principais frentes de evolução:

- consolidação do Dashboard UI v2;
- `placement_ready` totalmente oficial e exposto pelo backend;
- expansão multi-game;
- gerenciamento de Mods & Plugins por provider;
- métricas históricas e observabilidade;
- backup inteligente;
- broadcast e operações em lote;
- evolução da persistência e suporte a diferentes bancos;
- escalabilidade multi-datacenter;
- maior isolamento de execução das instâncias;
- segurança e hardening contínuos.

A documentação detalhada de decisões arquiteturais fica em `docs/` e os testes do repositório representam contratos importantes do comportamento atual.

---

## Contribuição

Issues e Pull Requests são bem-vindos. Para mudanças estruturais, prefira alterações pequenas, testáveis e compatíveis com a arquitetura Controller/Agent.

---

## Licença

Consulte o arquivo de licença disponível no repositório para os termos aplicáveis ao projeto.

---

<div align="center">

**Capivara DSM**  
Distributed Server Manager

</div>
