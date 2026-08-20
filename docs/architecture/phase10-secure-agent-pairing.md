# Fase 10 — Pareamento seguro Controller ↔ Agent

## Objetivo

Definir o fluxo oficial de enrollment remoto sem reutilizar credenciais administrativas e sem manter segredos de Agent em texto puro no Controller.

## 1. Token de pairing

O Controller gera um token criptograficamente aleatório e de uso único. O token:

- pertence a exatamente um Controller;
- possui expiração configurável (padrão: 15 minutos);
- é retornado em texto puro somente no momento da emissão;
- é persistido apenas como SHA-256 por ser um segredo aleatório de alta entropia;
- não contém senha administrativa, username ou dados de sessão;
- é invalidado no enrollment bem-sucedido.

## 2. Configuração inicial do Agent

A instalação do Agent recebe somente:

- `controller_url`;
- `pairing_token`.

Esses dados formam `AgentEnrollmentConfig`. O token existe somente para o primeiro registro e não é a identidade permanente do Agent.

## 3. Enrollment

Fluxo:

```text
Agent
  ↓ controller_url + pairing_token
Controller
  ↓ valida hash, Controller, expiração e uso único
registra Agent / node / fingerprint
  ↓
emite credential_id + credential_secret
  ↓
marca pairing token como consumido
```

O Agent entra em `pairing`, preservando a etapa administrativa de aprovação já existente no lifecycle.

O fingerprint informado pelo Agent é registrado tanto no inventário runtime quanto na credencial emitida. `public_key` é opcional nesta fase e já possui campo persistente.

## 4. Identidade permanente

A identidade permanente inicial usa `credential_type=opaque-v1`:

- `credential_id` identifica a credencial;
- `credential_secret` é mostrado ao Agent somente na emissão;
- o Controller persiste apenas `secret_hash`;
- autenticação posterior não utiliza mais o pairing token;
- a credencial pode ser revogada sem excluir o Agent.

A tabela `agent_credentials` inclui `public_key` e `credential_type`, permitindo evolução para identidade baseada em certificado/chave do Agent sem alterar `agent_id` ou o modelo de ownership.

## 5. Segurança

- pairing token não contém credencial administrativa;
- token expirado é rejeitado;
- token consumido é rejeitado em replay;
- segredo permanente incorreto é rejeitado;
- fingerprint divergente pode ser rejeitado na autenticação;
- customer não pode emitir token;
- Controller só pode emitir token dentro do próprio scope;
- revogação é escopada ao Controller proprietário.

## 6. Relação com heartbeat

A Fase 9 continua transport-neutral: `agent_heartbeat_api.py` recebe uma identidade Agent já autenticada. A Fase 10 fornece o mecanismo que produzirá essa identidade para a futura camada HTTP/TLS.

O pairing token jamais deve ser enviado em heartbeats depois do enrollment.

## 7. Próxima evolução

O contrato foi preparado para:

- chave privada gerada e mantida somente no Agent;
- public key registrada no Controller;
- certificado assinado/rotacionável;
- mTLS Controller ↔ Agent;
- rotação e revogação de credenciais;
- reconnect usando identidade permanente.
