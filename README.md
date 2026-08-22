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

A CLI pública do projeto é **`cap`**. O comando histórico `dsm` permanece somente como camada temporária de compatibilidade.

---

## Estado atual

O Capivara DSM possui uma base funcional para gerenciamento distribuído, incluindo:

- Controller, Agent e modo Híbrido;
- Agents Linux e Windows;
- enrollment, pairing seguro e heartbeat de Agents;
- localização de Agents por região e datacenter;
- placement distribuído;
- criação e gerenciamento de instâncias;
- reservas e administração de portas por Agent;
- runtime multi-game;
- catálogo de jogos e providers;
- instalação e gerenciamento via SteamCMD quando aplicável;
- observabilidade de CPU, memória, disco, rede e runtime;
- Universal Event Platform;
- Universal Configuration Platform;
- Universal Content Platform;
- Universal Smart Backup;
- Automation & Universal Broadcast;
- API em tempo real;
- Multi-Datacenter Federation;
- High Availability e Disaster Recovery;
- RBAC para administração e clientes;
- painel separado para clientes;
- instalação remota de Agents Linux via SSH;
- atualização e rollout de Agents;
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

- Regions e Datacenters;
- Agents;
- instalação de novos Agents;
- instalação remota via SSH;
- atualização e rollout;
- faixas de portas;
- localização;
- topologia visual.

```text
Controller
   └── Region
        └── Datacenter
             └── Agent
                  └── Instâncias
```

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

O placement considera a validade da infraestrutura e o estado operacional disponível:

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

Na instalação interativa de um **Controller** ou **Hybrid**, o instalador permite definir a Region e o Datacenter iniciais. Um **Agent puro** é associado posteriormente a uma topologia já existente pelo Controller.

---

## Banco de dados

O Controller utiliza uma camada de persistência para informações administrativas e operacionais, incluindo entidades como controllers, agents, customers, contracts, instances, ports, regions, datacenters, alerts, events e audit log.

Os backends suportados pelo instalador são:

```text
SQLite
PostgreSQL
MySQL
MariaDB
```

Na instalação interativa de Controller/Hybrid, o banco pode ser escolhido durante o setup. SQLite continua sendo a opção local simples; PostgreSQL é a opção recomendada para ambientes de produção e maior escala.

---

## Jogos e providers

O Runtime foi desenhado para não ficar limitado a um jogo específico.

Entre os fluxos já trabalhados no projeto estão:

- **DayZ** — Steam / SteamCMD;
- **Minecraft Java** — catálogo e providers, incluindo Modrinth;
- **Minecraft Bedrock** — provider de arquivo HTTP e resolver oficial;
- arquitetura extensível para novos jogos e providers.

A disponibilidade efetiva de cada operação depende do catálogo e do provider implementado para o jogo.

---

## Agents

### Linux

O Agent Linux pode ser instalado e pareado com o Controller. O Dashboard também suporta bootstrap remoto via SSH.

### Windows

O projeto possui Agent Windows próprio, com runtime, capabilities, inventário de rede e mecanismo de atualização correspondente.

---

## Portas de rede

As portas são administradas por Agent.

A alocação considera:

- faixa configurada para o Agent;
- reservas persistidas;
- portas realmente ocupadas no sistema operacional;
- requisitos do runtime/jogo;
- reserva atômica para evitar colisões.

A arquitetura prevê blocos de portas definidos conforme os requisitos de cada tipo de servidor, com reservas próprias por instância e preservação dessas reservas durante stop/restart.

---

## Segurança

O projeto inclui mecanismos como:

- autenticação do Dashboard;
- RBAC;
- pairing seguro de Agents;
- autenticação permanente para heartbeat;
- separação de permissões por função;
- validação de releases e atualização;
- auditoria de operações;
- proteção de migrations e restore;
- fencing e proteção contra split-brain em HA;
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
├── bin/                    # CLI cap e compatibilidade interna
├── install.sh              # Entrada do instalador
└── install-core.sh         # Núcleo da instalação Linux
```

---

# Instalação rápida

O instalador oferece três papéis:

```text
Controller  - Control Plane; não executa servidores de jogos localmente
Agent       - hospeda e executa as instâncias
Hybrid      - Controller + Agent na mesma máquina
```

> Os comandos abaixo são exemplos para Linux. Revise os requisitos e a release desejada antes de usar em produção.

## Opção 1 — instalar clonando o repositório

Instale Git caso ainda não esteja disponível e clone o projeto:

```bash
git clone https://github.com/EzequielRibeiro/Distributed-Server-Manager.git
cd Distributed-Server-Manager
```

Opcionalmente, confira a branch/commit que será instalado:

```bash
git status
git log -1 --oneline
```

Execute o instalador usando os arquivos do checkout local:

```bash
sudo ./install.sh --local
```

O modo interativo solicitará as informações pertinentes ao papel escolhido. Em Controller/Hybrid, isso inclui seleção do banco de dados e configuração inicial de Region/Datacenter.

Para validar o plano sem modificar o sistema:

```bash
./install.sh --dry-run --local
```

## Opção 2 — instalar a partir de um arquivo/pasta local

Se você recebeu o código-fonte ou um pacote extraído localmente, entre no diretório que contém `install.sh` e `install-core.sh`:

```bash
cd /caminho/para/Distributed-Server-Manager
```

Garanta que o instalador está executável:

```bash
chmod +x install.sh install-core.sh
```

Execute usando exclusivamente os arquivos locais:

```bash
sudo ./install.sh --local
```

Também é possível testar primeiro em dry-run:

```bash
./install.sh --dry-run --local
```

## Instalação a partir de uma GitHub Release

Quando o `install.sh` estiver disponível localmente, ele também pode buscar uma release oficial:

```bash
sudo ./install.sh --remote
```

Para solicitar uma tag específica:

```bash
sudo ./install.sh --version v2.0.0
```

A instalação remota depende da existência dos assets oficiais esperados pelo instalador para aquela release.

## Instalação não interativa

Os principais valores também podem ser definidos por variáveis de ambiente, por exemplo:

```bash
sudo env \
  DSM_NODE_ROLE=controller \
  DSM_DATABASE_DRIVER=sqlite \
  DSM_NON_INTERACTIVE=1 \
  ./install.sh --local
```

Para bancos de rede, utilize as variáveis documentadas pelo instalador, como `DSM_DATABASE_HOST`, `DSM_DATABASE_PORT`, `DSM_DATABASE_NAME`, `DSM_DATABASE_USER`, `DSM_DATABASE_PASSWORD_FILE` e `DSM_DATABASE_TLS`.

## Depois da instalação

A CLI pública é:

```bash
cap help
```

Para visualizar todos os comandos disponíveis:

```bash
cap help --all
```

O comando `dsm` existe apenas como compatibilidade temporária para instalações/scripts antigos e não deve ser usado como CLI principal em novas automações.

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
- migrations e múltiplos backends;
- build de release;
- pacotes dos Agents Linux e Windows;
- placement, infraestrutura e RBAC;
- regressões e cenários end-to-end;
- auditoria de componentes legados;
- release readiness.

O desenvolvimento prioriza modularização. Novas responsabilidades devem ser implementadas em módulos específicos em vez de aumentar arquivos centrais já extensos.

---

## Roadmap

A arquitetura v3 consolidou os principais blocos distribuídos: runtime, plataformas universais, automação, API em tempo real, federação multi-datacenter e HA/DR.

As próximas evoluções concentram-se em hardening contínuo, experiência operacional, expansão do catálogo multi-game, observabilidade, eficiência de escala e redução progressiva das camadas temporárias de compatibilidade.

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
