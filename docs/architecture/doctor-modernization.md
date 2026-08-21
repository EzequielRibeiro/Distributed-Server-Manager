# Modernização do Doctor do Capivara DSM

## Decisão arquitetural

O Doctor legado baseado em Bash, DayZ e LinuxGSM foi removido do código-fonte. O Capivara DSM não mantém LinuxGSM como camada de compatibilidade do Doctor.

O diagnóstico oficial é orientado aos recursos nativos do Capivara e separado por escopo:

- `cap infrastructure doctor`: infraestrutura distribuída do Controller/Hybrid;
- `cap agent doctor`: diagnóstico local do Agent;
- `cap instance doctor <instance-id>`: superfície reservada à evolução do diagnóstico por instância/runtime.

A CLI pública é `cap`. O antigo nome de comando `dsm` permanece apenas como wrapper temporário de compatibilidade e não deve ser utilizado em documentação ou novos procedimentos. Qualquer referência histórica a `dsm doctor` representa somente o período anterior à unificação e não é uma interface pública recomendada.

## Fronteira entre diagnóstico e mutação

`cap infrastructure doctor` é estritamente observacional. A execução normal não deve:

- executar migrations;
- inicializar ou alterar schema;
- persistir refresh de health;
- alterar Agent, topology, placement ou ranges;
- reparar permissões ou reiniciar serviços.

A única fronteira de mutação atualmente permitida é explícita:

```text
cap infrastructure doctor --reconcile
```

O modo `--reconcile` limita-se às reconciliações determinísticas expressamente implementadas pelo Doctor.

## Contrato público

O engine interno permanece em `database/infrastructure_doctor.py`. A superfície pública versionada fica em `database/infrastructure_doctor_contract.py` e é compartilhada por CLI e Dashboard.

Campos superiores do schema v1:

```json
{
  "schema_version": 1,
  "kind": "CapivaraInfrastructureDoctor",
  "scope": "infrastructure",
  "generated_at": "2026-08-20T22:00:00Z",
  "status": "healthy",
  "ready": true,
  "reconcile_mode": false,
  "repairs": [],
  "summary": [],
  "findings": [],
  "placement": {}
}
```

`status` possui somente três valores canônicos:

- `healthy`: sem findings warning/critical e infraestrutura pronta;
- `degraded`: existe ao menos um warning, sem condição critical;
- `critical`: existe finding critical ou a infraestrutura não está pronta.

Os findings usam severidades `info`, `warning` e `critical`. A apresentação humana pode usar rótulos próprios, mas integrações devem consumir `status` e `findings[].severity`.

## Dashboard

A API Python está em `dashboard/infrastructure_doctor_api.py`. Ela sempre executa o Doctor em modo read-only e não expõe reconciliação por GET.

O contrato HTTP oficial é:

```text
GET /api/infrastructure/doctor
```

O roteamento passa pela camada modular `dashboard/infrastructure_http.py`, que delega o endpoint do Doctor para `dashboard/infrastructure_doctor_http.py`. `dashboard/server.py` conserva apenas a adaptação HTTP genérica e não contém lógica de diagnóstico.

A transição baseada em cache foi encerrada. Não existem mais:

- `dashboard/api/doctor.sh`;
- `dashboard/workers/doctor_worker.sh`;
- `dashboard/workers/collect_doctor.sh`;
- `doctor_state.json` como estado obrigatório da Dashboard;
- campo `doctor` no agregado `dashboard_state.json`;
- worker periódico dedicado ao Doctor.

O Doctor passa a ser calculado sob demanda quando um consumidor autorizado requisita o endpoint moderno. Isso elimina escrita periódica de cache e evita executar diagnóstico apenas para manter um arquivo intermediário.

## Autorização

A leitura do Doctor de infraestrutura é permitida para perfis administrativos/operacionais do Controller (`admin`, `operator`, `controller`). Perfis `customer` não recebem o diagnóstico global de infraestrutura.

A rota GET da Dashboard nunca oferece `--reconcile`. Reconciliação continua restrita à CLI administrativa explícita.

## Fonte de verdade

A fonte de verdade do Doctor moderno são os repositórios e estados nativos consultados pelo engine Python. A Dashboard não mantém uma segunda fonte de verdade em JSON.

## Componentes removidos

Foram retirados do código-fonte todos os componentes do Doctor Bash histórico, incluindo adapters, analyzers, checks de servidor/mods/keys/permissões/disco, runners, contexto de instância, relatório e regras do diretório `doctor/`.

Também foram retirados os bridges temporários da Dashboard e a dependência de `doctor_state.json`.

Nenhum runtime novo deve reintroduzir `LINUXGSM_PATH`, `core/lgsm.sh` ou funções `lgsm_*` como dependência do Doctor. Diagnósticos específicos de jogos pertencem à superfície de diagnóstico por instância implementada sobre os runtimes/providers nativos do Capivara.
