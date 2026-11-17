# Minecraft Votifier: reserva TCP sob demanda

## Contrato
- **Vanilla e Bedrock:** sem suporte Votifier nem nova reserva.
- **Java com mods ou plugins:** Votifier é capacidade opcional, **desativada por padrão**. A reserva ocorre somente mediante pedido explícito `votifier_enabled=true` durante criação; o Controller valida runtime, pré-valida o Agent e utiliza a mesma transação e verificação de conflitos numéricos (TCP e UDP) que as portas do jogo.
- O bloco `block_size=4` e offsets 0, 1 e 2 permanecem inalterados por compatibilidade de instâncias antigas. O quarto número não é automaticamente reservado, nem recebe regra pública sem opt-in.
- O cliente precisa instalar uma implementação **compatível** de Votifier por mod/plugin e configurar **manualmente** a porta efetivamente atribuída. Reservar porta não instala ou configura o mod/plugin.

## Instâncias anteriores
`legacy_reservations` mantém válidas todas as reservas Votifier criadas antes desta alteração. Reconciliadores **nunca** removem ou backfillam portas Votifier somente por mudança no catálogo. Quando um cliente habilita a porta posteriormente, a reserva transacional prefere o offset +3 apenas se estiver totalmente desocupado; caso contrário, seleciona outra porta TCP livre dentro da faixa do Agent. A reserva numérica não pode colidir com porta TCP nem UDP de outra instância.

## Habilitar/desabilitar depois da criação
A área do cliente expõe controle apenas quando o usuário tem `settings.write`, o contrato permite mods/plugins e há **Agent híbrido local** verificável. É obrigatório parar a unidade `capivara-instance-<id>.service`. A identidade do Agent é verificada contra o estado híbrido local; manipulações em Agents remotos **não estão disponíveis** após a criação sem protocolo específico de atualização de rede no Agent.

Habilitar: commit da reserva no banco → sincronização do RuntimeSpec e da política de firewall com o Agent → confirmação de mesma porta no Agent. Se falhar a sincronização, a porta continua reservada e a UI informa pendência, evitando reutilização indevida.

Desabilitar: marcação de liberação pendente no banco → remoção dos bindings Votifier no Agent **parado** (mantendo a reserva no Controller) → verificação de que o serviço está carregado e inativo, que o Agent já não referencia a porta e que nenhum processo escuta nela → transação de exclusão da reserva. Qualquer falha mantém o número reservado; uma nova tentativa pode concluir a sincronização.

## Firewall e implantação
Linux/Windows geram a regra pública Votifier somente se `network_exposure.optional=true` **e** a reserva TCP está presente. O RuntimeSpec existente e seu `profile_context` recebem atualização de política, preservando demais parâmetros para migrações futuras.

O conjunto completo da implementação permanece em **PR #832**, dependente de **PR #827**. Não copiar o checkout inteiro para `/opt/dsm`, nem realizar release sem backup integral verificável do PostgreSQL e dos dados privados das instâncias e homologação da recuperação. Preservar DayZ existente.
