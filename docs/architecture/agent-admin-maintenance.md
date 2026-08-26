# Administração e diagnóstico de Agents

## Objetivo

Definir uma ferramenta administrativa para manutenção segura de Agents a partir do Controller/Dashboard. A ferramenta deve reduzir operações manuais no host remoto, impedir uso de shell arbitrário e reutilizar os contratos existentes de identidade, heartbeat, capabilities, runtime inventory, lifecycle e Doctor.

## Escopo

A área **Infraestrutura → Agents → Administrar Agent** deve permitir a usuários `admin` e `controller`:

1. consultar identidade e inventário;
2. alterar propriedades administrativas seguras;
3. executar diagnóstico completo;
4. revisar findings e recomendações;
5. rotacionar/reemitir credenciais através de fluxo controlado;
6. iniciar revinculação de Agent perdido;
7. validar prontidão para placement;
8. consultar versão, atualização, portas, storage e capabilities;
9. registrar toda operação em auditoria/eventos.

Não deve oferecer execução arbitrária de comandos do sistema operacional.

## Identidade: campos imutáveis e editáveis

### Imutáveis em edição normal

- `agent_id`
- `node_id`
- `fingerprint`
- `credential_id`
- `credential_secret`

Esses campos pertencem ao contrato de identidade e não devem aparecer como inputs editáveis.

### Editáveis por Admin/Controller

- nome administrativo do Agent;
- endereço anunciado (`advertise_address`), com validação;
- Region/Datacenter/Agent Location através do fluxo de topologia;
- faixas gerenciadas de portas através do módulo de port ranges;
- estado administrativo quando suportado pelo lifecycle (`active`, `disabled`, etc.);
- canal/política de atualização, quando aplicável.

Mudanças de topologia e portas devem continuar usando seus próprios serviços/repositórios, não updates SQL genéricos.

## Tela sugerida

```text
Agent: Node1                                  [Online]
agent-3357c...

[Visão geral] [Diagnóstico] [Rede/Portas] [Atualização] [Segurança]

Visão geral
  Nome administrativo       Node1                    [Editar]
  Controller                controller-main          somente leitura
  Node ID                   node-...                 somente leitura
  Fingerprint               sha256:...               somente leitura
  Hostname                  Node1
  Endereço anunciado        192.168.15.55            [Editar]
  Último heartbeat          há 12 s
  Versão                    2.x

Diagnóstico
  [Executar diagnóstico completo]

  Identidade                OK
  Credencial                OK
  Serviço                   OK
  Controller                OK
  Heartbeat                 OK
  Capabilities              OK
  Portas                    ATENÇÃO
  Storage                   OK
  Game data                 OK
  SteamCMD                  OK
  Atualização               OK
```

## Doctor remoto

O Linux Agent já possui o contrato local `CapivaraAgentDoctor`, executado por:

```bash
cap agent doctor
cap agent doctor --json
```

O diagnóstico administrativo deve reutilizar esse contrato em vez de duplicar regras no Dashboard.

### Fluxo proposto

```text
Admin/Controller
      |
      v
POST /api/admin/agents/{agent_id}/doctor
      |
      v
Controller cria comando tipado: agent.doctor
      |
      v
Agent recebe pelo canal autenticado existente
      |
      v
Executa Doctor local (sem shell arbitrário)
      |
      v
Retorna CapivaraAgentDoctor JSON
      |
      v
Controller persiste snapshot + evento + findings
      |
      v
Dashboard renderiza resultado
```

## Verificações mínimas

### Identidade e segurança

- `agent_id` presente e coerente;
- `node_id` presente e coerente;
- fingerprint local igual ao registrado no Controller;
- credencial permanente presente;
- credencial não revogada;
- Controller associado correto;
- pairing token ausente após enrollment;
- permissões esperadas do arquivo local de identidade;
- suporte a TLS/HTTPS validado quando habilitado.

### Serviço e heartbeat

- serviço do Agent ativo;
- processo principal vivo;
- Controller `/ping` alcançável;
- heartbeat recente;
- estado `active/online` coerente;
- latência/tempo de resposta dentro de limite operacional;
- relógio do host sem desvio excessivo.

### Inventário/runtime

- hostname;
- SO e arquitetura;
- versão Capivara;
- endereço anunciado;
- capabilities publicadas;
- runtimes disponíveis;
- recursos de CPU/RAM/storage;
- espaço livre em disco;
- diretórios de runtime acessíveis.

### Rede e portas

- port ranges configurados;
- ranges válidos e não sobrepostos;
- conflitos entre sockets locais e portas gerenciadas;
- endereço anunciado utilizável pelo Controller;
- Region/Datacenter/Location atribuídos quando exigidos pelo placement.

### Conteúdo e providers

- estado de game-data;
- jobs recentes com falha;
- SteamCMD instalado/funcional quando aplicável;
- runtime 32-bit do SteamCMD em Linux quando necessário;
- conta Steam configurada apenas quando um runtime exigir autenticação;
- Java/runtime dependencies coerentes com capabilities.

### Atualização

- versão instalada;
- canal configurado;
- release mais recente conhecida;
- update pendente;
- último update bem-sucedido ou falho.

## Resultado do diagnóstico

O resultado deve manter as severidades já usadas pelo Doctor:

- `healthy`: sem findings críticos ou warning;
- `degraded`: existe warning, mas o Agent ainda pode operar;
- `critical`: existe finding crítico e o Agent não deve ser considerado pronto.

A UI não deve transformar automaticamente todo warning em bloqueio de placement. A política de readiness deve continuar centralizada na camada apropriada.

## Renomear Agent

### API proposta

```http
PATCH /api/admin/agents/{agent_id}
Content-Type: application/json

{
  "name": "Node Limeira 01"
}
```

Regras:

- permitido somente a `admin` e `controller` dentro do escopo;
- nome obrigatório, trim, limite de comprimento;
- `agent_id`, `node_id`, Controller e fingerprint não podem ser enviados para alteração;
- atualizar `agents.name` e, se a arquitetura exigir, a representação administrativa do node sem modificar hostname físico;
- registrar `AGENT_ADMIN_UPDATED` com ator, Agent, campos alterados e timestamp.

O nome administrativo é diferente de `hostname`. Renomear o card da Dashboard não deve renomear o host Linux/Windows automaticamente.

## Revincular Agent

A Dashboard deve transformar o runbook manual em um fluxo guiado:

1. Admin seleciona **Revincular Agent**.
2. Sistema explica que a ação é para Agent instalado cuja credencial foi perdida no Controller.
3. Admin informa/valida `agent_id`, `node_id` e fingerprint recuperados do Agent.
4. Controller verifica conflitos de identidade.
5. Emite pairing token de uso único e curta duração.
6. Agent recebe o token por um canal administrativo seguro ou o operador executa um comando local curto.
7. Credencial antiga é substituída; IDs e fingerprint permanecem.
8. Controller aguarda enrollment e heartbeat.
9. Ao sucesso, executa Doctor automaticamente.
10. Registra `AGENT_RELINKED` e o resultado do diagnóstico.

A primeira versão pode manter a etapa 6 manual, mas deve evitar edição manual de JSON pelo operador.

## Rotação de credencial

A ação **Rotacionar credencial** deve ser distinta de **Revincular Agent**:

- rotação: Agent e Controller ainda confiam um no outro;
- revinculação: a confiança foi perdida em um dos lados.

A rotação ideal emite a nova credencial através do canal já autenticado, confirma o primeiro heartbeat com a nova identidade e só então revoga a credencial anterior.

## Auditoria e eventos

Toda ação administrativa deve produzir evento estruturado, no mínimo:

- `AGENT_ADMIN_UPDATED`
- `AGENT_DOCTOR_REQUESTED`
- `AGENT_DOCTOR_COMPLETED`
- `AGENT_CREDENTIAL_ROTATED`
- `AGENT_RELINK_STARTED`
- `AGENT_RELINKED`
- `AGENT_RELINK_FAILED`

Campos recomendados:

- `agent_id`
- `controller_id`
- ator (`username`/role)
- request/correlation id;
- resultado;
- findings/severidade quando aplicável;
- timestamp.

Nunca incluir pairing token ou credential secret nos eventos.

## RBAC

### admin

Acesso completo às ações administrativas.

### controller

Acesso aos Agents dentro de seu escopo de Controller.

### operator

Pode consultar diagnóstico e inventário se a política permitir, mas não renomear identidade, rotacionar credenciais ou executar revinculação.

### customer

Sem acesso à administração de Agents.

## Endpoints sugeridos

```text
GET   /api/admin/agents/{agent_id}
PATCH /api/admin/agents/{agent_id}
POST  /api/admin/agents/{agent_id}/doctor
GET   /api/admin/agents/{agent_id}/doctor/latest
POST  /api/admin/agents/{agent_id}/credential-rotate
POST  /api/admin/agents/relink
GET   /api/admin/agents/relink/{operation_id}
```

A implementação deve preferir serviços/repositórios específicos e manter `server.py/server_part*.py` apenas como composição/roteamento.

## Critérios de aceite

A ferramenta estará pronta quando for possível, sem SSH e sem SQL manual:

1. abrir um Agent na Dashboard;
2. alterar seu nome administrativo;
3. executar Doctor completo;
4. visualizar findings e parâmetros essenciais;
5. identificar credencial inválida/offline;
6. iniciar fluxo de revinculação sem trocar `agent_id`, `node_id` ou fingerprint;
7. concluir com heartbeat `online/active`;
8. executar Doctor pós-recuperação automaticamente;
9. consultar trilha de auditoria do que foi feito.
