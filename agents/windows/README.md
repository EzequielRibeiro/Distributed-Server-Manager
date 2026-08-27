# Capivara DSM Windows Agent

Instalação remota segura: consulte [o tutorial WinRM](../../docs/tutorial-instalacao-agent-windows-via-winrm.md).

Estrutura:

```text
agents/windows/
├── installer/
├── service/
├── gui/
├── runtime/
│   ├── adapters/
│   └── profiles/
├── updater/
└── config/
```

O Windows Agent usa o mesmo contrato distribuído do Linux Agent para enrollment, credenciais, heartbeat, health, capabilities, placement, atualização remota e operações de instância.

## Runtime parity

A paridade funcional do runtime distribuído é mantida por contratos comuns com o Controller. As diferenças ficam nas primitivas dependentes do sistema operacional: supervisão de processos/serviços, caminhos e executáveis dos perfis de jogos.

Superfícies disponíveis no Windows Agent:

- enrollment e credenciais permanentes;
- heartbeat, inventário, capabilities e remote Agent Update;
- inventário e lifecycle de instâncias (`status`, `doctor`, `start`, `stop`, `restart`);
- histórico idempotente e journal crash-consistent das operações;
- locks por instância e recuperação de operações interrompidas;
- provisioning assíncrono, materialização e reconciliação desired/observed;
- runtime health, métricas duráveis e Universal Event Platform com acknowledgement;
- configuração distribuída por revisão/checksum;
- Storage Pools administrados (`capivara.agent.storage`) com default, classe, prioridade, reserva e roots locais validados;
- telemetria de capacidade por Storage Pool e health/staleness das filas operacionais;
- Placement/provisioning com `storage_pool_id` e reserva lógica de capacidade definida pelo Controller;
- migração assíncrona de instância entre Storage Pools, com instância parada, lock, staging, SHA-256, commit atômico e rollback do RuntimeSpec;
- cleanup pós-migração explícito da cópia de origem, nunca automático, com nova validação local de ownership/pool/root e rejeição de links;
- conteúdo desired-state com validação de dependências, conflitos, checksum e extração segura;
- game-data com SteamCMD e provedores HTTP/archive/GitHub;
- Universal Smart Backup (`create`, `restore`, `delete`, retenção e consistência);
- broadcast distribuído com acknowledgement e fail-closed quando o adapter do jogo não oferece entrega ao jogador;
- adapter `windows-process` para processos de servidores de jogos;
- adapter `windows-service` para workloads supervisionados pelo Windows Service Control Manager;
- perfil DayZ nativo para Windows usando `DayZServer_x64.exe` e portas previamente reservadas pelo Controller.

O `windows-process` é a opção padrão para runtimes de jogos materializados pelo Agent. `windows-service` permanece disponível quando o workload já é exposto como serviço Windows.

A plataforma não envia comandos de shell arbitrários pelo Controller. Runtime specs, argumentos, paths, providers e operações são allowlisted/validados localmente, mantendo o mesmo princípio de segurança usado pelo Agent Linux.

## Interface administrativa opcional

Quando o Windows oferece Desktop Experience/Explorer e WPF, o instalador habilita automaticamente a interface administrativa local. Em Windows Server Core ou qualquer ambiente sem shell gráfico, o Agent permanece 100% headless e nenhuma dependência gráfica é necessária.

A GUI possui:

- visão geral com identidade, versão, Controller, saúde e Storage Pools;
- painel de atividades com métricas, reconciliação, configuração, conteúdo, backup, broadcast e game-data;
- inventário de instâncias com ações `status`, `doctor`, `start`, `stop` e `restart`;
- área de comandos que representa graficamente as operações administrativas locais suportadas;
- console administrativo restrito ao command catalog do Agent, sem shell arbitrária;
- visualizador de log persistente com acesso à pasta de logs;
- ícone na bandeja do Windows, com abertura rápida, atualização de saúde e acesso aos logs;
- atalho `Capivara Agent` na Área de Trabalho comum;
- inicialização do tray pelo Startup comum do Windows.

A instalação aceita `-GuiMode auto|on|off`. `auto` é o padrão. `on` exige que a máquina suporte GUI; `off` força operação headless mesmo em Windows com Desktop Experience.

O serviço não expõe `agent.json` para a sessão gráfica. O processo SYSTEM publica apenas `state/gui/snapshot.json`, sem `pairing_token`, `credential_id`, `credential_secret` ou `identity_nonce`. A sessão gráfica lê esse snapshot e o log. Quando uma ação administrativa precisa acessar estado protegido, ela usa um bridge local com UAC e executa somente comandos allowlisted em `admin_gui_backend.py`.

O log do Agent fica em `%ProgramData%\CapivaraAgent\logs\agent.log`, com rotação local quando ultrapassa 10 MiB. O supervisor continua sendo uma Scheduled Task SYSTEM; a GUI nunca substitui nem hospeda o runtime do Agent.

Instalações existentes recebem os componentes gráficos via self-update. Após atualizar, o updater reconcilia o launcher do serviço e executa a integração gráfica de forma idempotente.

## Gate de paridade

O workflow `Windows Agent Parity` executa os contratos em Linux e também nativamente em `windows-latest`. Ele valida lifecycle/provisioning, Storage Pools, configuração gerenciada, queue health, migração/cleanup, GUI/tray, parsing PowerShell e o pacote reproduzível. Os módulos do runtime e scripts de GUI/serviço são descobertos automaticamente por `release/build_windows_agent_package.py`, evitando que uma capability nova fique fora do ZIP de produção.

Produção usa o pacote imutável `capivara-agent-windows-X.Y.Z.zip` publicado na mesma GitHub Release do Controller. Ambientes offline podem usar o mesmo pacote extraído com `install-agent.ps1`.
