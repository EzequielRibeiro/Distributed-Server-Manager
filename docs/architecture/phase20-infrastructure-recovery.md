# Fase 20 — Recuperação e reconciliação de infraestrutura

## Objetivo

Preparar o Capivara para falhas e restaurações reais sem reconstruir topologia ou identidade por adivinhação.

O comando administrativo é:

```bash
cap infrastructure doctor
```

Saída estruturada:

```bash
cap infrastructure doctor --json
```

Reconciliação segura:

```bash
cap infrastructure doctor --reconcile
```

`--reconcile` aplica somente mudanças determinísticas derivadas de dados já conhecidos. Nesta fase isso inclui atualizar `health_status` a partir da idade do heartbeat. O comando nunca move instâncias, troca `agent_id`, recria credenciais, escolhe Region/Datacenter ou elimina duplicatas automaticamente.

## Situações cobertas

### Agent reinstalado / Agent duplicado

A fingerprint reportada é comparada entre identidades. A mesma fingerprint em mais de um `agent_id` gera `duplicate_agent_identity` e bloqueia readiness. A escolha da identidade válida exige decisão administrativa e revogação controlada da outra.

### Agent mudou de IP

O endereço é inventário dinâmico. Um novo heartbeat autenticado atualiza `agent_runtime_inventory.address`; a identidade continua sendo credencial + fingerprint, não IP.

### Agent perdeu configuração

Agent ativo sem heartbeat ou sem credencial permanente é reportado. O doctor não cria segredo automaticamente. O reparo indicado é novo pareamento controlado quando necessário.

### Controller reiniciado

O estado persistido permanece no banco. Ao executar o doctor, health é recalculado pela idade do heartbeat, e placement é reconstruído a partir da topologia persistida.

### Banco restaurado

O doctor usa `LEFT JOIN` para detectar referências quebradas mesmo quando um restore foi produzido com verificações de FK relaxadas. Controller/Agent/Location/Datacenter/Region órfãos são bloqueadores.

### Agent órfão

Agent sem Controller ou Node correspondente gera `agent_orphan`. Nenhuma instância é removida ou realocada automaticamente.

### Datacenter removido

Uma `agent_location` apontando para Datacenter inexistente gera `orphan_agent_location`. O operador precisa restaurar o Datacenter ou mover explicitamente o Agent, mantendo as instâncias vinculadas.

### Region desativada

Agents ligados a Datacenters de uma Region desativada permanecem cadastrados, mas deixam de ser elegíveis para placement. O doctor mostra `region_disabled_for_agent` e `Placement ... NOT READY` quando não houver alternativa elegível.

### Port allocation

Para cada Agent ativo, o doctor consulta a visão efetiva da Fase 16:

```text
agent_port_ranges
+
instance_ports
+
sockets reais observados
```

Faixa ausente gera warning; conflito persistente ou socket não administrado dentro da faixa gera blocker.

## Saída humana

Exemplo saudável:

```text
Controller           OK         1/1 active
Agents               OK         3/3 online
Locations            OK         3/3 active located
Regions              OK         1/1 active
Datacenters          OK         1/1 active
Port allocation      OK         conflicts=0, without_ranges=0
Placement            READY      eligible_agents=3
```

## Invariantes de segurança

1. Nenhuma reconciliação automática altera `instances.agent_id` ou `instances.node_id`.
2. Nenhuma localização é inventada.
3. Nenhuma credencial permanente é emitida pelo doctor.
4. Nenhum Agent duplicado é apagado automaticamente.
5. IP é atributo dinâmico; identidade não depende dele.
6. Region/Datacenter desativados bloqueiam novo placement, mas não destroem instâncias.
7. O comando pode ser executado após restart/restore sem depender de estado em memória do Controller.
