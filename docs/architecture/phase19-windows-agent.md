# Fase 19 — Agent Windows

## Objetivo

Adicionar Windows como plataforma de Agent sem criar um segundo protocolo distribuído.

Linux e Windows compartilham:

- enrollment por pairing token de uso único;
- credencial permanente;
- headers de autenticação;
- `/api/agent/enroll`;
- `/api/agent/heartbeat`;
- lifecycle e health;
- inventário de CPU/RAM/storage/network;
- capabilities primitivas;
- port allocation;
- atualização remota e rollout em lotes.

## Estrutura

```text
agents/windows/
├── installer/
│   ├── bootstrap-release.ps1
│   └── install-agent.ps1
├── service/
│   └── register-task.ps1
├── runtime/
│   ├── agent.py
│   ├── capabilities.py
│   ├── network_inventory.py
│   └── update_client.py
└── updater/
    └── updater.py
```

`agents/common/identity.py` é compartilhado pelas duas plataformas.

## Supervisor

A primeira implementação Windows usa uma Scheduled Task executada como `SYSTEM`, disparada no boot, com política de restart.

Essa escolha evita tornar WinSW/NSSM dependência obrigatória. O supervisor local poderá ser substituído futuramente por um serviço SCM nativo sem alterar o protocolo Controller ↔ Agent.

## Instalação

### GitHub Release

O Controller serve `/agent/install.ps1` fixando a mesma versão do Controller. O bootstrap:

1. baixa `capivara-agent-windows-X.Y.Z.zip`;
2. baixa `.sha256`;
3. valida SHA-256;
4. extrai o pacote;
5. executa `install-agent.ps1`;
6. gera identidade local;
7. grava configuração em `%ProgramData%\CapivaraAgent`;
8. protege o arquivo com ACL para `SYSTEM`/Administrators;
9. registra o supervisor;
10. inicia enrollment e heartbeat.

### Pacote local

O mesmo `install-agent.ps1` aceita o diretório extraído do pacote canônico. O resultado funcional é o mesmo da Release.

## Pacote

`release/build_windows_agent_package.py` produz de forma reprodutível:

- `capivara-agent-windows-X.Y.Z.zip`;
- `capivara-agent-windows-X.Y.Z.zip.sha256`;
- `capivara-agent-windows-X.Y.Z.manifest.json`.

O GitHub Release publica e gera provenance para o ZIP, assim como no Linux.

## Capabilities Windows

O Agent reporta primitivas técnicas, não nomes de jogos:

- `native-windows`;
- `powershell`;
- `steamcmd`;
- `java`;
- `docker`;
- `wine=false`;
- `backup=false` enquanto não houver command surface;
- `mod-management=false` enquanto não houver command surface.

O placement continua dirigido pelo catálogo de runtimes da Fase 17.1.

## Network inventory

Windows usa `netstat -ano` para observar portas TCP/UDP. A informação entra no mesmo `network_json` usado pelo Controller para calcular conflitos e disponibilidade efetiva.

## Atualização

O heartbeat recebe o mesmo objeto `update` usado no Linux. O runtime Windows inicia o updater como processo destacado sob o mesmo contexto `SYSTEM`, encerra o runtime atual e, depois da atualização, o updater dispara novamente a Scheduled Task.

ZIPs são validados contra path traversal antes da extração, além do checksum externo e hashes internos do manifest.

## Invariantes

1. Nenhuma API exclusiva de Windows é criada no Controller.
2. Pairing e credenciais têm o mesmo formato das demais plataformas.
3. O core de placement não conhece jogos específicos nem diferencia plataformas por hardcode de jogo.
4. Release e pacote local resultam no mesmo runtime instalado.
5. Windows não altera o lifecycle consolidado pelo Linux.
6. Nenhuma alteração direta é feita na instalação ativa do Controller em `/opt/dsm`.
