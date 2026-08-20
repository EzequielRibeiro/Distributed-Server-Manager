# Fase 11 — Instalação remota Linux

## Objetivo

Disponibilizar um caminho oficial e mínimo para instalar um Agent Linux remoto sem instalar o Controller completo como serviço ativo e sem fornecer credenciais administrativas ao host remoto.

## Estrutura

```text
agents/
├── common/
└── linux/
    ├── installer/
    ├── runtime/
    ├── services/
    └── README.md
```

## Comando entregue pelo Controller

O Controller gera um pairing token da Fase 10 e produz um comando no formato:

```text
curl -fsSL <controller>/agent/install.sh | sudo bash -s -- \
  --controller-url <controller> \
  --pairing-token <token>
```

O bootstrap é servido pelo Controller a partir da própria release instalada. Nenhuma senha de admin/controller é incluída.

## Cadeia de confiança do pacote

```text
Controller bootstrap
  -> GitHub Release oficial
  -> archive .tar.gz
  -> checksum .tar.gz.sha256
  -> SHA-256 validado
  -> arquivos Agent obrigatórios validados
  -> instalação
```

A Fase 11 valida integridade por SHA-256. Assinatura criptográfica de artefatos pode ser adicionada em fase posterior sem alterar o contrato do Agent.

## Identidade local

Antes do primeiro contato, o instalador cria:

- `agent_id` opaco;
- `node_id` opaco;
- hostname;
- fingerprint SHA-256;
- nonce local.

A configuração inicial é gravada em `/etc/capivara-agent/agent.json`, modo `0600`, propriedade do usuário de serviço `capivara-agent`.

## Enrollment e ativação

```text
install
  -> systemd
  -> Agent runtime
  -> POST /api/agent/enroll (pairing token)
  -> permanent credential
  -> remove pairing token local
  -> POST /api/agent/heartbeat (permanent credential)
  -> pairing -> active
  -> heartbeat contínuo
```

O pairing token é de uso único e deixa de existir na configuração depois do enrollment. O primeiro heartbeat autenticado demonstra posse da identidade permanente e conclui automaticamente a transição `pairing -> active`.

## Endpoints

- `GET /agent/install.sh` — bootstrap Linux da release do Controller;
- `POST /api/agent/enroll` — troca token de uso único por identidade permanente;
- `POST /api/agent/heartbeat` — autenticação permanente + inventário/heartbeat.

## Systemd

`capivara-agent.service` usa:

- usuário/grupo `capivara-agent`;
- `Restart=always`;
- `NoNewPrivileges=true`;
- `ProtectSystem=strict`;
- escrita limitada a `/etc/capivara-agent` e `/var/lib/capivara-agent`.

## Invariantes

1. Nenhuma senha administrativa é enviada ao Agent.
2. O pairing token não é reutilizado após enrollment.
3. A credencial permanente não é substituída pelo token em heartbeats.
4. O pacote deve passar por validação de SHA-256 antes da instalação.
5. `agents.status=disabled` continua administrativo e não é modificado por heartbeat.
6. O Agent instalado não modifica diretamente a instalação Controller em `/opt/dsm`.
7. HTTPS é obrigatório como política de produção para o transporte remoto.
