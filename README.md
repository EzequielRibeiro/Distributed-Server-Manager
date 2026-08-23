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

O **Capivara DSM (Distributed Server Manager)** é um gerenciador distribuído de servidores de jogos. O projeto começou como um gerenciador dedicado ao DayZ e evoluiu para uma arquitetura **multi-game, multi-host e multi-datacenter**, com separação entre **Controller**, **Agents**, catálogo técnico e instâncias pertencentes aos contratos dos clientes.

```text
Cliente / Administrador
        │
        ▼
     Controller
        │
        ├── Region
        │    └── Datacenter
        │         └── Agent
        │              ├── game-data compartilhado
        │              └── Instâncias de jogos
        │
        └── Clientes / Contratos / Alertas / Eventos
```

A CLI pública do projeto é **`cap`**. O comando histórico `dsm` permanece somente como camada temporária de compatibilidade.

---

## Estado atual

A base funcional inclui Controller/Agent/Hybrid, Agents Linux e Windows, enrollment e heartbeat, Regions/Datacenters, placement distribuído, clientes e contratos, runtime multi-game, portas por Agent, catálogo v2, providers, SteamCMD, game-data distribuído, observabilidade, eventos, configuração, conteúdo, backup, automação, API em tempo real, RBAC, atualização de Agents e Dashboard Web v3.

A arquitetura de **Catálogo → Game Data → Runtime/Resource Profile → Contrato → Instance** está concluída nas dez etapas planejadas, incluindo parâmetros de startup, templates, perfis de recursos, reutilização sob demanda, integridade, repair, reconciliação e File Manager seguro com paridade Linux/Windows.

---

## Dashboard Web v3

A interface administrativa usa navegação lateral e áreas separadas para Visão Geral, Administração, Infraestrutura, Servidores, Operações, Observabilidade e Sistema.

### Infraestrutura

Regions, Datacenters e Placement possuem visão própria. A página **Agents** representa a frota; **Adicionar Agent** concentra enrollment/instalação; o detalhe do Agent concentra telemetria e operações específicas.

### Instâncias

A página de Instâncias representa apenas servidores já materializados. A criação de nova instância parte do **contexto do cliente e de um contrato válido**, e não do Catálogo de Jogos.

### Catálogo de Jogos

O Catálogo é uma ferramenta administrativa do Control Plane. Ele **não cria instâncias de clientes**. Sua responsabilidade é definir e preparar tudo que pode ser reutilizado quando um contrato solicita uma nova instância:

- definição do jogo/runtime, provider e versão;
- instalação, atualização, verificação e reparo de **game-data** nos Agents;
- File Manager de game-data confinado à raiz do runtime;
- parâmetros de processo/startup persistentes;
- environment, variáveis, shutdown e timeouts;
- templates de configuração materializados na instância;
- perfis de recursos;
- conteúdo adicional compatível;
- disponibilidade e inventário por Agent;
- versões, integridade, reconciliação e recuperação.

A arquitetura separa quatro entidades:

```text
Game Catalog Definition
        │
        ├── Runtime Definition
        ├── Runtime Policy / Templates
        └── Resource Profiles
                │
                ▼
Agent / game-data compartilhado
                │
                ▼
Cliente → Contrato → Criar Instância
                │
                ▼
Placement → ensure game-data → materializar instância
                │
                ├── reutiliza base íntegra existente
                └── instala/repara quando ausente ou inválida
```

A operação de provisionamento usa `ensure`: quando o game-data necessário já está íntegro no Agent escolhido, ele é reutilizado sem reinstalação. Quando está ausente ou inválido, o provider instala/repara antes da materialização.

O File Manager administrativo suporta listar, ler, editar, criar, renomear, enviar e excluir dentro do game-data, com proteção contra path traversal e symlink escape, limite de 1 MiB para edição textual e 32 MiB para upload.

Perfis de recursos são definidos tecnicamente pelo Catálogo e autorizados pelo contrato. Exemplo: um único Minecraft pode oferecer `standard` com 8 GB de RAM e 25 GB de armazenamento e `large` com 16 GB de RAM e 30 GB, sem duplicar o jogo no catálogo. O perfil acompanha o provisionamento e fica disponível para Placement e Runtime Policy.

A especificação detalhada está em [Catálogo, Game Data, Runtime e Perfis de Recursos](docs/architecture/catalog-game-data-runtime-resource-architecture.md) e o histórico de implantação em [Cronograma da arquitetura de Catálogo](docs/roadmaps/catalog-game-data-architecture-implementation-plan.md).

---

## Arquitetura

### Controller

Responsável por autenticação/RBAC, clientes e contratos, catálogo, topologia, placement, coordenação de provisionamento, persistência, eventos, alertas, Dashboard e distribuição de operações para Agents.

### Agent

Responsável pelo host que executa as cargas: inventário, game-data compartilhado, runtime local das instâncias, métricas, portas, providers locais como SteamCMD quando aplicável e comunicação autenticada com o Controller.

### Híbrido

Executa Controller e Agent na mesma máquina mantendo os mesmos contratos distribuídos.

### Placement

Um Agent só é candidato quando topologia, saúde, capabilities, portas e recursos são compatíveis. O perfil de recursos resolvido pelo contrato acompanha a solicitação para impedir que uma instância seja provisionada com orçamento fora do permitido.

---

## Banco de dados

O Controller usa uma camada de persistência para controllers, agents, customers, contracts, instances, ports, regions, datacenters, alerts, events e auditoria. O instalador suporta **SQLite, PostgreSQL, MySQL e MariaDB**. PostgreSQL é recomendado para produção e maior escala.

Instalações novas usam o schema consolidado em `database/schemas/`. Credenciais de bancos de rede são mantidas em arquivo protegido e não são exibidas ou gravadas na configuração principal.

---

## Jogos e providers

O Runtime é genérico. Entre os fluxos existentes estão DayZ/Steam, Minecraft Java com múltiplos runtimes/providers, Minecraft Bedrock e uma arquitetura extensível para novos jogos.

O `RuntimeDefinition` v2 descreve processo, requisitos, artifact/provider, instalação e rede. `CatalogRuntimePolicy` acrescenta argumentos, environment, variáveis, templates, shutdown e timeouts administráveis. `ConfigurationProfile` continua descrevendo arquivos conhecidos/editáveis. `GameResourceProfiles` define limites técnicos reutilizáveis de memória, armazenamento, CPU e limites opcionais.

---

## Segurança

O projeto inclui autenticação do Dashboard, RBAC, pairing seguro de Agents, validação de releases, auditoria, proteção de persistência e isolamento progressivo. O Game Data File Manager é confinado à raiz derivada do runtime, rejeita traversal e symlink escape e limita payloads. Runtime Policy usa vetor de argumentos em vez de exigir shell arbitrário e templates são materializados apenas dentro da árvore privada da instância.

---

## Estrutura principal

```text
Distributed-Server-Manager/
├── agents/                 # Agents Linux e Windows
├── backup/                 # Backup e restore
├── catalog/                # Catálogo v2, runtimes, schemas e perfis
├── core/                   # Núcleo e regras compartilhadas
├── dashboard/              # Backend e Dashboard Web v3
├── database/               # Persistência e schemas
├── docs/                   # Arquitetura, roadmaps e runbooks
├── installer/              # Providers e instalação de conteúdo
├── release/                # Build e empacotamento
├── runtime/                # Runtime e estado operacional
├── systemd/                # Serviços Linux
├── tests/                  # Contratos e gates E2E
├── bin/                    # CLI cap
├── install.sh
└── install-core.sh
```

---

## Instalação rápida

```bash
git clone https://github.com/EzequielRibeiro/Distributed-Server-Manager.git
cd Distributed-Server-Manager
sudo ./install.sh --local
```

Para validar o plano sem modificar o sistema:

```bash
./install.sh --dry-run --local
```

O instalador oferece os papéis `controller`, `agent` e `hybrid`. Em Controller/Hybrid também configura banco e topologia inicial. Para releases, `sudo ./install.sh --remote` usa os assets oficiais esperados pelo instalador.

Depois da instalação, use:

```bash
cap help
cap help --all
```

---

## Desenvolvimento e qualidade

O CI valida Bash, PowerShell, JSON, Python, JavaScript, installer/updater, CLI, catálogo, builds de release, Agents Linux/Windows, placement, RBAC e cenários end-to-end. O workflow **Catalog Architecture** adiciona um gate dedicado às etapas 5–10, incluindo Runtime Policy, templates, integrity/reconciliation e paridade do Game Data File Manager.

Novas responsabilidades devem ser implementadas em módulos específicos em vez de aumentar arquivos centrais extensos como `dashboard/server.py`.

---

## Roadmap

O ciclo de arquitetura do Catálogo foi concluído em **10/10 etapas**: auditoria/modelo, remodelagem da UI, inventário distribuído, File Manager seguro, parâmetros de runtime, materialização de templates, manutenção/integridade, integração com provisionamento, reconciliação/recuperação e paridade Linux/Windows com gate final.

Consulte [docs/roadmaps/catalog-game-data-architecture-implementation-plan.md](docs/roadmaps/catalog-game-data-architecture-implementation-plan.md).

### Tutoriais operacionais

- [Instalar um Agent Linux remotamente via SSH](docs/tutorial-instalacao-agent-via-ssh.md)
- [Instalar servidor DayZ para um cliente em um Agent remoto](docs/tutorial-instalacao-dayz-agent-remoto.md)

---

## Contribuição

Issues e Pull Requests são bem-vindos. Para mudanças estruturais, prefira alterações pequenas, testáveis e compatíveis com a arquitetura Controller/Agent.

---

## Licença

Consulte o arquivo de licença disponível no repositório para os termos aplicáveis ao projeto.

<div align="center">

**Capivara DSM**  
Distributed Server Manager

</div>
