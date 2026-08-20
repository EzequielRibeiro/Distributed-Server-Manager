# Fase 17 — Capabilities do Agent

## Objetivo

Fazer o placement selecionar somente Agents que comprovadamente conseguem executar o runtime e as ferramentas exigidas pela instância.

## Heartbeat

O Linux Agent detecta e reporta capabilities factuais, atualmente incluindo:

- `native-linux`
- `systemd`
- `steamcmd`
- `docker`
- `wine`
- `minecraft-java`
- `minecraft-bedrock`
- `dayz`
- `backup`
- `mod-management`

Ferramentas externas são detectadas no host. A ausência de uma ferramenta é reportada como `false`, não presumida como disponível.

## Perfis técnicos

`core/placement_requirements.py` converte o pedido de criação em requisitos técnicos. Exemplos iniciais:

- DayZ: `native-linux + steamcmd + dayz` e 10 UDP contíguas.
- Minecraft Java: `native-linux + minecraft-java` e 1 TCP.
- Minecraft Bedrock: `native-linux + minecraft-bedrock` e 1 UDP.

Os perfis descrevem requisitos de execução. Thresholds de CPU/RAM/storage podem vir do request/catalog e não são tratados como sizing universal fixo.

## Recursos

A Fase 17 compara capacidade informada no heartbeat:

- logical CPU threads;
- RAM total;
- storage livre no filesystem raiz.

Essa checagem representa capacidade mínima do host. Pressão dinâmica/overcommit e reserva quantitativa de CPU/RAM são evoluções posteriores do scheduler.

## Pipeline de placement

```text
lifecycle active
+ health online
+ Region/Datacenter válidos
+ capability necessária
+ runtime compatível
+ capacidade mínima
+ portas disponíveis
= Agent elegível
```

Somente depois o scorer existente escolhe entre os Agents elegíveis conforme região, latência e carga de instâncias.

## Compatibilidade e segurança

Um Agent sem inventário não satisfaz requisito explícito de capability/runtime. Isso é fail-closed: desconhecido não significa compatível.
