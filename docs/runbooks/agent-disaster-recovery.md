# Recuperação de desastre de um Agent em nova máquina

## Objetivo

Este runbook cobre a perda física total de um host Agent: incêndio, falha catastrófica, roubo, perda de disco ou qualquer situação em que a instalação anterior não possa mais ser acessada.

Este cenário é diferente de um simples revínculo. No revínculo, a máquina e a identidade local ainda existem. Na recuperação de desastre, a máquina original desapareceu e uma nova máquina precisa assumir a função operacional do Agent perdido.

## Princípio arquitetural

Um Agent pode manter banco de dados e estado local para execução, cache, filas, inventário e reconciliação, mas **não deve ser a única fonte de verdade** para informações que precisam sobreviver à perda do host.

O Controller deve continuar sendo a fonte autoritativa para:

- Customer e `customer_code`;
- contratos e limites;
- vínculo Customer ↔ Instance;
- identidade lógica da Instance;
- vínculo Instance ↔ Agent;
- Region / Datacenter / placement;
- estado administrativo e RBAC;
- histórico de eventos e auditoria que não seja estritamente local;
- referência dos backups disponíveis.

O banco local do Agent deve ser recuperável a partir do Controller, de backups externos e de reconciliação. Se um vínculo de cliente ou contrato existir somente no banco local do Agent, a arquitetura não é tolerante à perda total desse host.

## O que precisa existir fora do Agent

Para reconstruir um Agent em hardware novo, o sistema deve manter fora do host perdido:

1. metadados autoritativos das instâncias no Controller;
2. configuração declarativa necessária para recriar cada runtime;
3. catálogo/runtime definition usado para reinstalar o jogo;
4. reservas e políticas de portas que possam ser recalculadas;
5. backups de dados não reproduzíveis das instâncias;
6. inventário dos backups e checksums;
7. histórico da identidade lógica do Agent;
8. trilha de credenciais emitidas/revogadas;
9. localização lógica do Agent (Region / Datacenter / grupo de serviço).

Dados reproduzíveis, como binários do servidor baixáveis novamente por Steam, Mojang, GitHub ou outro provider, não precisam obrigatoriamente fazer parte do backup completo. Dados não reproduzíveis devem possuir cópia fora do host.

Exemplos de dados não reproduzíveis:

- saves/worlds;
- bancos de dados do jogo;
- arquivos de configuração alterados pelo cliente;
- mods/plugins locais que não possam ser obtidos novamente de uma origem confiável;
- chaves ou arquivos específicos da instância quando aplicável;
- uploads do cliente;
- dados persistentes de aplicações auxiliares.

## Identidade lógica x identidade física

Para suportar substituição de hardware, a arquitetura deve distinguir:

- `agent_id`: identidade lógica administrada pelo Controller;
- `node_id`: identidade lógica/topológica associada ao Agent;
- fingerprint: identidade observada da instalação/máquina atual;
- credential: segredo da instalação atual.

Em uma recuperação de desastre, a nova máquina **não deve reutilizar o segredo permanente da máquina destruída**.

O fluxo recomendado preserva o `agent_id` lógico, quando o administrador explicitamente escolhe **Substituir Agent perdido**, mas registra:

- fingerprint anterior como histórico/retirado;
- novo fingerprint como instalação ativa;
- credenciais antigas como revogadas;
- nova credencial emitida exclusivamente para a nova instalação;
- data, usuário e motivo da substituição.

Isso permite que contratos, placement e referências administrativas continuem apontando para o mesmo Agent lógico sem fingir que o hardware novo é a mesma instalação criptográfica.

## Fluxo recomendado — Substituir Agent perdido

### 1. Declarar o Agent antigo como perdido

Na Dashboard administrativa:

```text
Infraestrutura → Agents → <Agent> → Zona de recuperação → Declarar host perdido
```

A operação deve:

- colocar o Agent em estado `lost` ou equivalente;
- impedir novos placements;
- revogar todas as credenciais permanentes do Agent antigo;
- congelar alterações automáticas enquanto a recuperação estiver em andamento;
- registrar `AGENT_DISASTER_DECLARED`.

### 2. Escolher a estratégia

O administrador deve poder escolher entre:

#### A. Substituir o mesmo Agent lógico

Usar quando a nova máquina assumirá o lugar operacional da antiga no mesmo Datacenter/localização.

O `agent_id` lógico é preservado e uma nova instalação física é vinculada a ele.

#### B. Migrar as instâncias para outro Agent existente

Usar quando a prioridade é restaurar rapidamente os servidores em outro host saudável.

As instâncias são reassociadas pelo Controller e restauradas a partir dos backups externos. O Agent perdido pode permanecer `retired/lost`.

## 3. Preparar a nova máquina

Instale o sistema operacional suportado e execute o instalador normal do Agent, mas selecione o modo de recuperação quando estiver disponível:

```text
Adicionar Agent → Recuperar/Substituir Agent existente
```

A nova instalação deve gerar sua própria identidade física/fingerprint e nunca copiar cegamente `/etc/capivara-agent/agent.json` da máquina antiga.

## 4. Autorizar a substituição no Controller

O Controller deve emitir um token de recuperação de uso único vinculado a:

- `agent_id` esperado;
- Controller esperado;
- operação de disaster recovery;
- prazo curto de validade;
- usuário administrativo que autorizou a operação.

Ao consumir o token, o Controller deve verificar que o Agent está em estado de recuperação e registrar o novo fingerprint.

## 5. Criar nova credencial

A nova máquina recebe uma credencial permanente nova.

As credenciais da máquina perdida permanecem revogadas. Mesmo que o disco antigo reapareça ou seja recuperado por terceiros, ele não deve conseguir autenticar novamente no Controller.

## 6. Reconstruir o estado local do Agent

O Agent novo deve executar um `reconcile` inicial com o Controller.

O Controller envia ou disponibiliza o estado esperado:

```text
Agent lógico
  ├─ localização
  ├─ capabilities esperadas
  ├─ instâncias atribuídas
  ├─ runtime definitions
  ├─ contratos/referências necessárias
  ├─ políticas de portas
  └─ referências de backup
```

O Agent recria seu banco/estado operacional local a partir desse estado autoritativo. O objetivo é evitar depender de uma cópia binária do banco perdido para recuperar a topologia administrativa.

## 7. Reinstalar os runtimes reproduzíveis

Para cada Instance atribuída, o Agent deve:

1. validar requirements do jogo;
2. reservar/recalcular portas;
3. baixar novamente os artefatos reproduzíveis;
4. recriar diretórios e permissões;
5. reaplicar configuração declarativa;
6. preparar o runtime sem iniciar ainda os serviços que dependem de restore.

## 8. Restaurar os dados persistentes

Para cada Instance, selecione o backup externo mais recente considerado íntegro.

O sistema deve validar:

- Instance ID do backup;
- checksum;
- data/hora;
- versão/schema quando aplicável;
- compatibilidade com o runtime que será restaurado.

Depois restaure saves, configurações, uploads e demais dados persistentes.

## 9. Executar Doctor antes de liberar produção

O novo Agent deve executar Doctor completo, validando pelo menos:

- identidade lógica e nova identidade física;
- enrollment e credencial;
- serviço do Agent;
- Controller alcançável;
- heartbeat;
- runtime inventory;
- endereço anunciado;
- CPU, RAM e armazenamento;
- capabilities;
- SteamCMD e dependências quando aplicável;
- faixas/conflitos de portas;
- runtimes e diretórios das instâncias;
- backups restaurados;
- versão do Agent;
- estado de atualização.

Nenhuma Instance deve voltar automaticamente a produção se houver finding crítico relacionado à sua integridade.

## 10. Reconciliar e iniciar instâncias

Após Doctor aprovado:

1. Controller muda o novo host para `active`;
2. Agent executa reconcile final;
3. instâncias são iniciadas de forma controlada;
4. status real volta ao Controller;
5. timeline registra recuperação e restore;
6. placement volta a considerar o Agent elegível.

## Estado final esperado

```text
Controller
   │
   ├── Customer / Contract preservados
   ├── Instance IDs preservados
   ├── Agent lógico preservado (quando modo replacement)
   ├── credencial antiga revogada
   └── novo fingerprint/credential ativos
             │
             ▼
       Nova máquina
             │
             ├── Agent reinstalado
             ├── banco/estado local reconstruído
             ├── runtimes reinstalados
             ├── dados persistentes restaurados
             └── heartbeat + Doctor OK
```

## Backup obrigatório para tolerância a desastre

Se queremos garantir recuperação após perda total do host, o backup não pode residir exclusivamente no próprio Agent.

O Capivara deve suportar uma política de backup externo/off-host, por exemplo:

```text
Agent
  │
  ├── snapshot local temporário
  │
  └── envio para storage externo
          │
          ├── outro servidor
          ├── NAS
          ├── object storage S3-compatible
          └── storage do Datacenter
```

O Controller mantém o catálogo de backups e sua associação com cada Instance.

## RPO e RTO

A política deve permitir definir:

- **RPO (Recovery Point Objective):** quanto de dados podemos perder, por exemplo 15 minutos, 1 hora ou 24 horas;
- **RTO (Recovery Time Objective):** quanto tempo uma Instance pode ficar indisponível até ser restaurada.

Esses objetivos determinam frequência de backup, retenção, tamanho de storage e prioridade da recuperação.

## Ferramenta administrativa planejada

A Dashboard deverá oferecer uma ação específica:

```text
Infraestrutura
  → Agents
    → <Agent perdido>
      → Recuperação de desastre
        → Substituir por nova máquina
```

O assistente deverá:

1. marcar o host antigo como perdido;
2. bloquear placement;
3. revogar credenciais antigas;
4. listar instâncias afetadas;
5. mostrar último backup válido de cada uma;
6. emitir token seguro de replacement;
7. acompanhar enrollment da nova máquina;
8. reconstruir estado local;
9. reinstalar runtimes;
10. restaurar backups;
11. executar Doctor;
12. iniciar instâncias;
13. concluir com relatório de recuperação e auditoria.

## Regra de arquitetura

**Customer, contratos, vínculos e identidade das instâncias não podem depender exclusivamente do banco local do Agent.**

O Agent é o executor distribuído. O Controller mantém a verdade administrativa e o storage externo protege os dados persistentes. Essa separação é o que permite que uma máquina inteira desapareça e o serviço seja reconstruído em outro hardware.
