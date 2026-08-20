# Capivara DSM Windows Agent

Estrutura:

```text
agents/windows/
├── installer/
├── service/
├── runtime/
├── updater/
└── config/
```

O Windows Agent usa o mesmo protocolo de enrollment, credenciais, heartbeat, health, capabilities, port allocation e remote updates do Linux Agent. A diferença fica restrita a instalação, coleta do host e supervisão local.

Produção usa o pacote imutável `capivara-agent-windows-X.Y.Z.zip` publicado na mesma GitHub Release do Controller. Ambientes offline podem usar o mesmo pacote extraído com `install-agent.ps1`.
