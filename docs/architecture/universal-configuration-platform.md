# C2 — Universal Configuration Platform

## Objetivo

C2 cria uma fonte de verdade única para configuração distribuída do Capivara. O Controller mantém configuração versionada e auditável; Agents recebem a configuração efetiva pelo heartbeat autenticado e persistem localmente apenas o material resolvido necessário ao runtime.

```text
Admin / Controller
      │
      ▼
Universal Configuration Store
      │
      ├── global
      ├── agent
      └── instance
      │
      ▼
Resolver
(global < agent < instance)
      │
      ▼
Authenticated heartbeat
      │
      ▼
Agent managed-configuration
      │
      └── configuration_state ACK
```

C2 não substitui arquivos de bootstrap necessários para iniciar Controller ou Agent. Ele passa a ser a plataforma canônica para configuração operacional mutável após enrollment.

## Contrato

`core/configuration_platform.py` define `CapivaraConfiguration` schema version 1.

Campos:

- `scope_type`: `global`, `agent` ou `instance`;
- `scope_id`: obrigatório em Agent/Instance e ausente em global;
- `namespace`: nome estável e independente de jogo;
- `value`: objeto JSON;
- `checksum`: SHA-256 do JSON canônico;
- `revision`: versão monotônica por documento.

Namespaces são genéricos, por exemplo:

```text
runtime.policy
runtime.limits
backup.policy
monitoring.defaults
network.policy
mail.smtp
```

Configuração específica de um jogo pode existir em namespace próprio, mas o mecanismo base não conhece nenhum jogo.

## Hierarquia e resolução

A precedência é determinística:

```text
global
  ↓ override
agent
  ↓ override
instance
```

Merge é recursivo para objetos. Valores escalares/listas do escopo mais específico substituem o valor anterior.

O Controller produz `CapivaraResolvedConfiguration` contendo:

- target (`agent` ou `instance`);
- namespace;
- valor efetivo;
- checksum da resolução;
- referências das revisões que participaram da resolução.

## Persistência

Migration `033_universal_configuration.sql` existe em:

- SQLite;
- MySQL/MariaDB;
- PostgreSQL.

Tabelas:

- `configurations`: estado desejado atual;
- `configuration_revisions`: histórico imutável;
- `agent_configuration_state`: projeção do que cada Agent confirmou como aplicado.

Alterar um documento gera nova revisão. Escrever o mesmo conteúdo é idempotente e não cria nova revisão.

## Segurança de secrets

C2 deliberadamente não armazena secrets brutos no documento universal. Chaves com semântica de `password`, `secret`, `token`, `credential` ou `private_key` são rejeitadas.

Secrets devem aparecer somente como referência:

```json
{
  "password_ref": "secret://smtp/primary"
}
```

A resolução futura dessas referências pertence ao Secret Provider/Vault e não deve transformar o banco de configuração em cofre de credenciais.

## Agent transport

No heartbeat o Agent envia `configuration_state`. O Controller responde com `configuration_commands` resolvidos para o Agent e suas instâncias.

O Agent persiste documentos em:

```text
CAPIVARA_AGENT_STATE_DIR/managed-configuration/
  agent/<agent-id>/<namespace>.json
  instance/<instance-id>/<namespace>.json
```

A gravação é atômica (`temp + fsync + replace`) e arquivos usam permissão restrita. O Agent envia ACK por referência de `configuration_id/revision/checksum` no heartbeat seguinte.

## Eventos

C2 usa C1 para registrar mudanças administrativas com `CONFIGURATION_UPDATED`. O evento contém IDs, scope, namespace, revision e checksum, mas não replica o conteúdo completo do documento.

## CLI

```text
cap config-store list
cap config-store get --scope global runtime.policy
cap config-store set --scope agent --scope-id <agent> runtime.policy --value-json '{...}'
cap config-store history <configuration-id>
cap config-store resolve --agent <agent> [--instance <instance>]
```

O nome `config-store` é separado do comando legado `cap config`, que continua representando configuração local/bootstrap até migração explícita.

## HTTP

```text
GET  /api/configurations
POST /api/configurations
```

Filtros GET suportam `scope`, `scope_id`, `namespace` e `limit`. `resolve=true&agent_id=...` retorna a projeção efetiva. A API global exige role `admin` ou `controller`.

## Relação com configurações legadas

Arquivos em `config/` permanecem como bootstrap/compatibilidade nesta fase. C2 não os importa automaticamente porque muitos misturam secrets, paths locais e defaults históricos. A migração deve ser namespace por namespace, preservando semântica e removendo dados sensíveis do store universal.

## Critério de conclusão

C2 está concluída quando CI prova:

- contrato e secret policy;
- paridade de migrations;
- revisão histórica e idempotência;
- merge global → Agent → Instance;
- distribuição autenticada pelo heartbeat;
- aplicação local atômica e ACK;
- CLI e API administrativas;
- integração com C1 via evento de alteração;
- inclusão do cliente de configuração no pacote Linux Agent.
