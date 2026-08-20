# Fase 5 — Placement Readiness

## Objetivo

Transformar a capacidade de realizar placement em um conceito explícito,
derivado e explicável do Capivara DSM.

`placement_ready` não é persistido no banco. Ele é calculado a partir do estado
real da infraestrutura.

## Contrato agregado

`RegistryRepository.topology_status()` passa a retornar os contadores antigos e
os elementos necessários ao placement:

```json
{
  "controllers": 1,
  "agents": 2,
  "customers": 0,
  "instances": 0,
  "regions": 1,
  "datacenters": 1,
  "agent_locations": 2,
  "eligible_agents": 2,
  "placement_ready": true,
  "placement_reason": null,
  "placement_reasons": []
}
```

Campos auxiliares de diagnóstico também são expostos:

- `pending_agents`: Agents em `pending` ou `pairing`;
- `unlocated_agents`: Agents sem Agent Location.

## Elegibilidade

Um Agent é elegível somente quando toda a cadeia existe e está ativa:

```text
Controller active
    ↓
Agent active
    ↓
Agent Location active
    ↓
Datacenter active
    ↓
Region active
```

O agregado global é considerado pronto quando `eligible_agents > 0`.

Um Agent adicional incompleto não torna a plataforma globalmente indisponível
se pelo menos um outro Agent continuar elegível.

## Diagnóstico explicável

Quando nenhum Agent é elegível, o status inclui razões estáveis:

- `no_agents`: nenhum Agent registrado no Controller;
- `agent_pending`: existe Agent em `pending`/`pairing`;
- `missing_location`: existe Agent sem Agent Location;
- `missing_datacenter`: nenhum Datacenter está cadastrado;
- `missing_region`: nenhuma Region está cadastrada;
- `no_eligible_agents`: existem Agents, mas nenhum satisfaz toda a cadeia ativa.

`placement_reason` contém a razão primária e `placement_reasons` contém a lista
ordenada completa de bloqueios relevantes.

Exemplo:

```json
{
  "agents": 1,
  "pending_agents": 1,
  "unlocated_agents": 1,
  "regions": 0,
  "datacenters": 0,
  "eligible_agents": 0,
  "placement_ready": false,
  "placement_reason": "agent_pending",
  "placement_reasons": [
    "agent_pending",
    "missing_location",
    "missing_datacenter",
    "missing_region",
    "no_eligible_agents"
  ]
}
```

## Separação de responsabilidades

- `core/placement_readiness.py`: prontidão de um Agent individual;
- `core/placement_diagnostics.py`: diagnóstico agregado puro;
- `database/location_repository.py`: candidatos de placement;
- `database/placement_status_repository.py`: snapshot agregado backend-independent;
- `database/registry_repository.py`: facade pública por `topology_status()`.

Essa separação permite que CLI, installer, Dashboard e futuras APIs consumam o
mesmo contrato sem duplicar regras.
