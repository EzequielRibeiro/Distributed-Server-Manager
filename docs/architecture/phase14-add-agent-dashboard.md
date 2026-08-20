# Fase 14 — Dashboard Adicionar Agent

## Objetivo

Transformar a área existente `Infraestrutura → Agents` no ponto oficial para iniciar e acompanhar a instalação de um Agent remoto.

## Fluxo

```text
Adicionar Agent
  ↓
Sistema (Linux / Windows planejado)
  ↓
Método (GitHub Release / Pacote local)
  ↓
Controller (quando necessário)
  ↓
Region
  ↓
Datacenter
  ↓
Gerar instalação
  ↓
Aguardando Agent
  ↓
Pareando
  ↓
Validando
  ↓
Online
```

Linux é funcional. Windows aparece na interface como capacidade planejada e o backend responde explicitamente `501` enquanto o runtime Windows não existir.

## Instalação persistente

A migration `022_agent_installation_tracking.sql` acrescenta ao pairing token metadados não secretos de instalação:

- `platform`;
- `install_method`;
- `region_id`;
- `datacenter_id`;
- `agent_id` após enrollment.

O segredo do pairing token continua armazenado somente como hash. O `installation_id` exposto ao Dashboard é o ID do registro de pairing, não o token.

## Métodos

### GitHub Release

Usa o bootstrap oficial da Fase 12 e pacote imutável da mesma versão do Controller.

### Pacote local

O Dashboard entrega a instrução para executar o `install-agent.sh` do pacote canônico já transferido ao host, conforme Fase 13.

## Tracking

`GET /api/agents/installations/status?installation_id=...` deriva o estado de dados persistentes:

- token ainda não consumido → `waiting`;
- token consumido / Agent em pairing → `pairing`;
- Agent administrativo ativo mas saúde ainda não online → `validating`;
- heartbeat online → `online`.

A associação de UI é secundária ao boundary de segurança: falha de tracking após um enrollment bem-sucedido nunca invalida a credencial permanente nem incentiva replay do pairing token.
