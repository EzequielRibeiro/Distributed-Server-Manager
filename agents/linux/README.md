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
    │   ├── agent.py
    │   ├── capabilities.py
    │   ├── network_inventory.py
    │   ├── local_cli.py
    │   ├── game_data_client.py
    │   ├── game_data_executor.py
    │   ├── game_data_state.py
    │   └── update_client.py
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

## CLI local

O pacote Linux instala `local_cli.py` no runtime do Agent e expõe `/usr/local/bin/cap` como link para essa CLI. O instalador se recusa a sobrescrever um `cap` já existente que não pertença ao Agent.

A superfície local é estritamente observacional:

```text
cap agent status
cap agent info
cap agent health
cap agent heartbeat
cap agent capabilities
cap agent network
cap agent ports show
cap agent ports check
cap agent game-data list
cap agent game-data status <game>
cap agent jobs [--active] [--limit N]
cap agent jobs show <job-id>
cap agent logs [--lines N]
cap agent doctor
```

Todos os comandos aceitam `--json` quando aplicável. `cap agent doctor` não usa a database do Controller, não executa migrations, não faz heartbeat e não altera configuração. Ele compõe identidade/enrollment, serviço, conectividade ao `/ping` do Controller, CPU/RAM/disco, capabilities, sockets locais, ranges de portas e um resumo do estado local de game-data/jobs.

`cap agent game-data` lê o inventário persistido pelo executor local em `game-data-state/`. `cap agent jobs` combina jobs transitórios em `game-data-jobs/` com resultados finais sanitizados em `game-data-jobs/history/`. A consulta não dispara instalação, atualização, verificação ou heartbeat.

Quando o Controller confirma um resultado final, o Agent preserva somente um resumo operacional sanitizado antes de remover `request.json` e `result.json`. Logs permanecem separados. Credenciais e o `RuntimeSelection` completo não são copiados para o histórico.

`cap agent ports show/check` é somente leitura. A autoridade para `ports set` continua no Controller/Hybrid. Enquanto o Controller ainda não sincroniza ranges gerenciados para o arquivo local do Agent, a CLI informa `configured=false` em vez de inventar um range.

A CLI nunca imprime `credential_secret` nem outras credenciais permanentes.

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
├── agent/runtime/capabilities.py
├── agent/runtime/network_inventory.py
├── agent/runtime/local_cli.py
├── agent/runtime/update_client.py
├── agent/runtime/game_data_client.py
├── agent/runtime/game_data_executor.py
├── agent/runtime/game_data_state.py
├── services/capivara-agent.service
├── config/README.md
├── VERSION
└── manifest.json
```

O Agent não recebe nem armazena senha administrativa do Controller.

## Produção

O `controller_url` deve utilizar HTTPS em produção. A credencial `opaque-v1` é a etapa de transição para a identidade baseada em chave/certificado prevista pela arquitetura de pareamento seguro.
