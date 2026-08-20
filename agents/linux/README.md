# Capivara DSM — Linux Agent

Estrutura dedicada ao Agent Linux remoto.

```text
agents/
├── common/
│   └── identity.py
└── linux/
    ├── installer/
    │   ├── bootstrap-release.sh
    │   └── install-agent.sh
    ├── runtime/
    │   └── agent.py
    ├── services/
    │   └── capivara-agent.service
    └── README.md
```

## Produção — GitHub Release

1. O Controller emite um pairing token de uso único.
2. O Controller apresenta um comando contendo apenas URL do Controller e pairing token.
3. `GET /agent/install.sh` entrega `bootstrap-release.sh` fixado na versão do próprio Controller.
4. O bootstrap consulta a GitHub Release daquela tag, nunca `main`.
5. Baixa `capivara-agent-linux-X.Y.Z.tar.gz` e seu `.sha256`.
6. Valida SHA-256 antes de extrair.
7. Executa o `install-agent.sh` que está dentro do pacote.
8. O Agent gera identidade, faz enrollment, remove o pairing token, inicia heartbeat e conclui `pairing -> active`.

## Desenvolvimento / offline

`release/build_agent_package.sh HEAD dist` constrói o mesmo pacote canônico usado na Release.
Após transferir/extrair o pacote em uma rede isolada, execute seu `install-agent.sh` com Controller URL e pairing token.

O instalador local não acessa GitHub e não executa `git clone`. Ele valida `manifest.json`, `VERSION` e hashes internos antes de instalar.

## Paridade

Release e modo local convergem para o mesmo payload:

```text
capivara-agent-linux-X.Y.Z/
├── install-agent.sh
├── agent/common/identity.py
├── agent/runtime/agent.py
├── services/capivara-agent.service
├── config/README.md
├── VERSION
└── manifest.json
```

O Agent não recebe nem armazena senha administrativa do Controller.

## Produção

O `controller_url` deve utilizar HTTPS em produção. A credencial `opaque-v1` é a etapa de transição para a identidade baseada em chave/certificado prevista pela arquitetura de pareamento seguro.
