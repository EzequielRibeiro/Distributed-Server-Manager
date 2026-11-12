# Minecraft Server Pack — gate operacional isolado (#1013 / PR #1031)

**Gate de release independente:** `release_authorized=false` não é alterado por este recurso. Não usar uma observação de log `Done`, nem a publicação do bundle isoladamente, como comprovante de saúde. A homologação do ambiente e a revisão da PR seguem obrigatórias.

## Fonte da prova

1. O Agent autentica seu heartbeat e recebe do Controller o manifesto e a revisão atual de sua instância.
2. O observador compara loader, hashes e JARs físicos com o manifesto; sem equivalência, não produz atestação funcional.
3. O verificador Linux vincula o processo Java à unidade systemd e ao diretório do runtime, exige evento `Done` atual, identifica a porta TCP reservada em `server.properties`, comprova que o inode LISTEN é mantido pela JVM e obtém resposta de status Minecraft Java via loopback. Revalida o mesmo PID e horário de início após a consulta.
4. O Controller valida o escopo do Agent autenticado, instância, revisão, SHA-256, PID, época do `boot_observation` e porta TCP `game` reservada para o nó da instância no banco do Controller. Guarda as evidências como evento de auditoria, nunca como autorização de release.
5. O read model de cliente requer, cumulativamente, alinhamento de metadados, atestado físico do commit, observação física atual, boot consultivo atual, atestação funcional recente (até 90 segundos) e saúde positiva recente do Agent (até 180 segundos). Observações negativas posteriores invalidam as anteriores; drift, hold e offline/stale bloqueiam o estado `ready`.

## Feature flag

`DSM_SERVERPACK_HEALTH_PROMOTION_ENABLED=1` — **desligada por padrão**. É avaliada no processo Controller que serve o read model do cliente. Não habilitar em produção antes da homologação operacional completa e aprovação explícita. Para testar, habilitar somente em Controller descartável, com SQLite e instância separadas. A flag `DSM_CONTENT_HOLD_INSTANCE_IDS` continua impedindo `ready` se contiver o ID da instância.

O frontend só deve mostrar "Saúde operacional confirmada" quando a projeção do Controller indicar `health_gate=ready`; caso contrário informa que a liberação está bloqueada. A confirmação do estado na interface não publica release, não faz merge, não modifica flags e não executa restart.

## Evidências ainda obrigatórias

- Prova real em instalação isolada com processo Java do ATM11 oficial, boot testemunhado na revisão correspondente e `ready` no navegador autenticado.
- Morte/restart durante e após a prova, mod JAR alterado, manifesto/revisão divergente, agente offline, health stale, hold ativo, rollback e queda de conexão. Todos devem bloquear o estado em no máximo o TTL de observação, sem apresentar resultado antigo como atual.
- Teste do gate FULL + workflows GitHub Actions sobre o HEAD exato e revisão formal da PR.
