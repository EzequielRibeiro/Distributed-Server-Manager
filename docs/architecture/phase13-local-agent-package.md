# Fase 13 — Instalação do Linux Agent por pacote/diretório local

## Objetivo

Permitir desenvolvimento, homologação, datacenters isolados e instalação offline sem alterar o comportamento final do Agent instalado por GitHub Release.

## Formato canônico

O pacote é construído por `release/build_agent_package.sh` e possui:

```text
capivara-agent-linux-X.Y.Z/
├── install-agent.sh
├── agent/
│   ├── common/
│   │   └── identity.py
│   └── runtime/
│       └── agent.py
├── services/
│   └── capivara-agent.service
├── config/
│   └── README.md
├── VERSION
└── manifest.json
```

Esse é o mesmo diretório que existe dentro do artefato de GitHub Release.

## Construção local

A partir de um checkout oficial:

```text
release/build_agent_package.sh HEAD dist
```

gera o `.tar.gz`, `.sha256` e manifest externo. O diretório extraído pode ser transferido para uma rede isolada.

## Instalação offline

Dentro do pacote extraído, o administrador executa o `install-agent.sh` passando apenas:

- Controller URL;
- pairing token.

Também é aceito `--package-dir` para homologação/automação.

O instalador local deliberadamente não possui dependência de GitHub, `git clone` ou branch remota. Ele valida:

1. `manifest.json`;
2. `kind=CapivaraAgentPackage`;
3. `platform=linux`;
4. versão do manifest contra `VERSION`;
5. presença dos arquivos obrigatórios;
6. SHA-256 interno de cada arquivo listado.

Depois instala exatamente os mesmos arquivos em:

```text
/opt/capivara-agent
/etc/capivara-agent
/var/lib/capivara-agent
/etc/systemd/system/capivara-agent.service
```

## Paridade Release × local

O teste `tests/agent_package_test.sh` garante que o pacote local é reprodutível e que `identity.py`, `agent.py` e a unit systemd empacotados são byte a byte iguais aos arquivos rastreados no mesmo commit do repositório.

Portanto os dois caminhos convergem:

```text
GitHub Release ─┐
                ├─> pacote canônico ─> install-agent.sh ─> Agent instalado
Diretório local ┘
```

## Invariantes

1. Não existe implementação alternativa do Agent para modo offline.
2. O mesmo manifest e o mesmo instalador são usados em Release e local.
3. Segredos de pairing são fornecidos no momento da instalação, nunca empacotados.
4. O resultado funcional e o layout instalado são iguais nos dois canais.
5. Redes sem GitHub continuam capazes de instalar e parear contra um Controller acessível localmente.
