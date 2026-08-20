# Fase 15 — Administração de localização

## Objetivo

Administrar a posição operacional de cada Agent usando a topologia existente `Region → Datacenter → Agent Location`.

A interface de `Agents` expõe:

- Agent;
- Region;
- Datacenter;
- Public Host;
- Latitude/Longitude opcionais;
- Status da localização.

A Region não é gravada diretamente em `agent_locations`: ela é derivada do Datacenter escolhido. Isso impede combinações inconsistentes como um Datacenter pertencente a uma Region diferente da selecionada.

## Proteção de instâncias

Localização é metadado de placement, não ownership de instância.

O boundary `agent_location_safety.py` captura os IDs das instâncias do Agent antes da alteração, executa somente a atualização de `agent_locations` e confirma que a lista permanece idêntica depois.

A resposta inclui:

```json
{
  "instances_preserved": 2,
  "instance_ids_preserved": ["instance-a", "instance-b"]
}
```

Nenhuma operação de localização executa delete, recriação ou troca de `instances.agent_id`/`instances.node_id`.

## Placement

Uma mudança de Region/Datacenter modifica onde o Agent será considerado para novos placements. Instâncias existentes permanecem no Agent. Operações futuras de migração de instância deverão possuir um fluxo próprio e explícito; não serão efeito colateral da edição de localização.

## RBAC

Mantém o contrato existente:

- `admin`: qualquer Agent;
- `controller`: somente Agents de seu `scope_id`;
- customer: proibido.
