# Fase 17.1 — Generic Game Placement Requirements

## Objetivo

Remover do core de placement qualquer conhecimento explícito sobre jogos específicos.

O Controller deve decidir elegibilidade a partir de contratos genéricos presentes nas definições de runtime do catálogo.

## Princípio

```text
RuntimeDefinition
        ↓
requirements / process / artifact / network / placement
        ↓
PlacementRequirements
        ↓
Agent capabilities + resources + ports
        ↓
Eligibility Engine
```

`core/placement_requirements.py` não contém nomes de jogos, AppIDs ou regras específicas de títulos.

## Inferência genérica

O parser pode inferir requisitos técnicos de campos já existentes:

- `process.engine=native` + suporte Linux → `native-linux`;
- `process.engine=java` → `java`;
- `process.engine=docker|container` → `docker`;
- `process.engine=wine|wine64` → `wine`;
- `artifact.provider=steam` → `steamcmd`;
- `network.allocation=block` + `block_size` → requisito de bloco contíguo por protocolo.

## Extensão declarativa

Quando a definição existente não expressar tudo que o placement precisa, o runtime pode declarar:

```json
{
  "placement": {
    "runtime": "capability-opcional",
    "capabilities": ["capability-extra"],
    "ports": [
      {"protocol": "udp", "count": 4, "contiguous": true}
    ],
    "resources": {
      "cpu_threads": 4,
      "ram_bytes": 8589934592,
      "storage_bytes": 21474836480
    }
  }
}
```

Esse contrato não exige alteração do core para adicionar novos jogos.

## Capabilities do Agent

O Agent reporta primitivas factuais de host/runtime, e não nomes de jogos inferidos de forma otimista:

- `native-linux`
- `systemd`
- `steamcmd`
- `java`
- `docker`
- `wine`
- `backup` (quando realmente implementado)
- `mod-management` (quando realmente implementado)

A compatibilidade com um jogo é consequência da combinação entre RuntimeDefinition e essas primitivas.

## Universalidade

O teste `phase17_1_generic_placement_requirements_test.py` cria uma definição de um jogo fictício (`future-game`) em um catálogo temporário e valida capabilities, recursos e portas sem modificar nenhuma tabela Python ou branch condicional do core.

## Segurança de compatibilidade

Um runtime desconhecido não recebe requisitos inventados. Se não houver definição de catálogo disponível, o core preserva somente requisitos de recursos explicitamente fornecidos pela requisição.

A reserva atômica definitiva de portas continua sendo responsabilidade do subsistema de alocação; o eligibility engine apenas verifica capacidade antes do scorer.
