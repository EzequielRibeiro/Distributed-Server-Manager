# Fase 16 — Agent Port Allocation no Placement

## Objetivo

Transformar a política de portas por Agent em requisito obrigatório de elegibilidade antes do placement de uma nova instância.

## Fontes de verdade

- `agent_port_ranges`: faixas TCP/UDP administradas pelo Controller.
- `instance_ports`: reservas persistentes pertencentes às instâncias DSM.
- `agent_runtime_inventory.network_json`: sockets TCP/UDP observados pelo próprio Agent Linux.

O Controller não copia reservas para `network_json`. O inventário observado é apenas telemetria; as reservas DSM continuam autoritativas em `instance_ports`.

## Disponibilidade efetiva

Para cada faixa ativa:

```text
occupied = reserved_by_DSM ∪ observed_OS_sockets
available = capacity - occupied
```

Um socket já coberto por uma reserva DSM válida não é contado duas vezes. Socket observado dentro de uma faixa administrada sem reserva correspondente é exposto como conflito `os_socket`.

Além de `capacity`, `reserved` e `available`, o resumo calcula `largest_contiguous_available`, necessário para jogos que exigem blocos contíguos.

## DayZ

O perfil técnico inicial de DayZ exige um bloco contíguo de 10 portas UDP. Essa regra é de elegibilidade; a reserva atômica definitiva continua pertencendo ao subsistema de alocação de portas quando a instância for criada.

## Ordem de elegibilidade

```text
Agent active
  → topology active
  → health online
  → resources
  → capabilities/runtime
  → port capacity
  → placement scorer
```

A checagem de disponibilidade não substitui a reserva atômica. Ela evita escolher um Agent obviamente incapaz antes da transação final de criação.

## Compatibilidade

Agents legados sem heartbeat continuam compatíveis somente para placements sem requisitos técnicos explícitos. Quando um jogo exige portas/capabilities/runtime, ausência de telemetria não é considerada evidência de suporte.
