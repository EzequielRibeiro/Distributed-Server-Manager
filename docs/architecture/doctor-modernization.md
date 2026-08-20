# Modernização do Doctor do Capivara DSM

## Decisão arquitetural

O Doctor legado baseado em Bash, DayZ e LinuxGSM foi removido do código-fonte. O Capivara DSM não mantém LinuxGSM como camada de compatibilidade do Doctor.

O diagnóstico oficial é orientado aos recursos nativos do Capivara e separado por escopo:

- `cap infrastructure doctor`: infraestrutura distribuída do Controller/Hybrid;
- `cap agent doctor`: diagnóstico local do Agent, planejado para a etapa seguinte;
- `cap instance doctor <instance-id>`: diagnóstico de runtime/instância, planejado para evolução posterior.

`cap doctor` não é um alias válido. `dsm doctor` também não executa mais o Doctor antigo e apenas informa que o administrador deve usar `cap infrastructure doctor`.

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

A árvore histórica `doctor/` foi removida. Entretanto, `dashboard/server.py` ainda possui consumidores do estado agregado histórico. Para não deixar a Dashboard permanentemente degradada durante a extração progressiva de `server.py`, a ponte de apresentação introduzida em A2.3/A2.4 permanece temporariamente:

- `dashboard/api/doctor.sh` apenas encaminha para a API Python moderna;
- `dashboard/workers/doctor_worker.sh` apenas publica o contrato moderno;
- `dashboard/workers/collect_doctor.sh` apenas atualiza o cache moderno;
- `doctor_state.json` é cache de compatibilidade, nunca fonte de verdade.

Esses arquivos não contêm checks DayZ/LinuxGSM e não fazem parte do Doctor legado. Eles serão removidos quando `/api/infrastructure/doctor` for ligado diretamente ao roteamento modular da Dashboard e o campo histórico for retirado de `dashboard/server.py`, sem aumentar ainda mais esse arquivo.

## Autorização

A leitura do Doctor de infraestrutura é permitida para perfis administrativos/operacionais do Controller (`admin`, `operator`, `controller`). Perfis `customer` não recebem o diagnóstico global de infraestrutura.

## Fonte de verdade

A fonte de verdade do Doctor moderno são os repositórios e estados nativos consultados pelo engine Python. Qualquer `doctor_state.json` existente durante a transição é apenas cache de apresentação.

## Componentes removidos

Foram retirados do código-fonte todos os componentes do Doctor Bash histórico, incluindo adapters, analyzers, checks de servidor/mods/keys/permissões/disco, runners, contexto de instância, relatório e regras do diretório `doctor/`.

Nenhum runtime novo deve reintroduzir `LINUXGSM_PATH`, `core/lgsm.sh` ou funções `lgsm_*` como dependência do Doctor. Diagnósticos específicos de jogos pertencem ao futuro `cap instance doctor`, implementado sobre os runtimes/providers nativos do Capivara.
