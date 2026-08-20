# Capivara DSM — Linux Agent

Estrutura dedicada ao Agent Linux remoto.

```text
agents/
├── common/
│   └── identity.py
└── linux/
    ├── installer/
    │   └── install-agent.sh
    ├── runtime/
    │   └── agent.py
    ├── services/
    │   └── capivara-agent.service
    └── README.md
```

## Fluxo

1. O Controller emite um pairing token de uso único.
2. O Controller apresenta um comando contendo apenas a URL do Controller e o pairing token.
3. O bootstrap servido pelo próprio Controller baixa uma release oficial.
4. O SHA-256 publicado com a release é validado antes da extração.
5. Apenas o runtime necessário ao Agent é instalado em `/opt/capivara-agent`.
6. A identidade local é gerada e persistida em `/etc/capivara-agent/agent.json` com modo `0600`.
7. `capivara-agent.service` inicia o runtime.
8. O Agent troca o pairing token por uma credencial permanente.
9. O pairing token é removido da configuração local.
10. O primeiro heartbeat autenticado conclui `pairing -> active`.
11. Heartbeats seguintes utilizam somente a credencial permanente.

O Agent não recebe nem armazena senha administrativa do Controller.

## Produção

O `controller_url` deve utilizar HTTPS em produção. A credencial `opaque-v1` é a etapa de transição para a identidade baseada em chave/certificado prevista pela arquitetura de pareamento seguro.
