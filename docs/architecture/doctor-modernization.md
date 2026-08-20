# Modernização do Doctor do Capivara DSM

## Decisão arquitetural

O Doctor legado baseado em Bash, DayZ e LinuxGSM está em processo de extinção. O Capivara DSM não manterá LinuxGSM como camada de compatibilidade do Doctor.

O diagnóstico oficial passa a ser orientado aos recursos nativos do Capivara e separado por escopo:

- `cap infrastructure doctor`: infraestrutura distribuída do Controller/Hybrid;
- `cap agent doctor`: diagnóstico local do Agent, planejado para a etapa seguinte;
- `cap instance doctor <instance-id>`: diagnóstico de runtime/instância, planejado para evolução posterior.

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

Os findings usam severidades `info`, `warning` e `critical` conforme a evolução dos checks. A apresentação humana pode usar rótulos próprios, mas integrações devem consumir `status` e `findings[].severity`.

## Dashboard

A API Python está em `dashboard/infrastructure_doctor_api.py`. Ela sempre executa o Doctor em modo read-only e não expõe reconciliação por GET.

O contrato HTTP moderno é definido por `dashboard/infrastructure_doctor_http.py` para:

```text
GET /api/infrastructure/doctor
```

Durante a transição A2.3/A2.4, o endpoint histórico `/api/doctor` continua existindo como adaptador de transporte, mas sua fonte já é o Doctor Python moderno. O arquivo `dashboard/api/doctor.sh` não lê mais `runtime/state/doctor.json`.

Da mesma forma, `dashboard/workers/doctor_worker.sh` e `collect_doctor.sh` permanecem temporariamente apenas para manter consumidores antigos de `doctor_state.json`, porém já não carregam `core/lgsm.sh` nem executam checks LinuxGSM. Ambos publicam o contrato moderno.

A remoção física desses wrappers e da árvore Bash antiga pertence às etapas A2.5/A2.6.

## Autorização

A leitura do Doctor de infraestrutura é permitida para perfis administrativos/operacionais do Controller (`admin`, `operator`, `controller`). Perfis `customer` não recebem o diagnóstico global de infraestrutura.

## Fonte de verdade

`doctor_state.json`, quando ainda produzido durante a transição, é somente cache/compatibilidade de apresentação. Ele não é fonte de verdade.

A fonte de verdade do Doctor moderno são os repositórios e estados nativos consultados pelo engine Python.
