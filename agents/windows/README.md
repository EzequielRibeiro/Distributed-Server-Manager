# Capivara DSM Windows Agent

Estrutura:

```text
agents/windows/
├── installer/
├── service/
├── runtime/
│   └── adapters/
├── updater/
└── config/
```

O Windows Agent usa o mesmo protocolo de enrollment, credenciais, heartbeat, health, capabilities, port allocation e remote updates do Linux Agent.

## Runtime parity

A paridade com o runtime distribuído Linux está sendo implementada por contratos, preservando diferenças apenas onde o sistema operacional exige implementação própria.

Já disponível no Windows Agent:

- enrollment e credenciais permanentes;
- heartbeat, inventário e capabilities;
- remote Agent Update;
- inventário local de instâncias;
- `instance_command` / `instance_result` no mesmo contrato do Controller;
- lifecycle `status`, `doctor`, `start`, `stop` e `restart`;
- histórico idempotente de comandos;
- adapter allowlisted `windows-service`, baseado no Windows Service Control Manager.

Próximos blocos de paridade: provisioning/materialization, reconciliation/recovery, runtime health/metrics/events, configuração distribuída, conteúdo/game-data, backup e broadcast.

Produção usa o pacote imutável `capivara-agent-windows-X.Y.Z.zip` publicado na mesma GitHub Release do Controller. Ambientes offline podem usar o mesmo pacote extraído com `install-agent.ps1`.
