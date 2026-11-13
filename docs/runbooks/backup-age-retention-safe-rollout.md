# Backup por idade: 14 dias + ultimo confirmado (#1013)

## Escopo e ativacao

O comportamento antigo de `keep_single_operational=true` no Controller agenda a
exclusao dos backups anteriores **depois** de receber um novo backup concluido.
O Agent com `keep_single_operational=true` deixa o Controller decidir quais
backups excluir; nao remove nada durante a criacao.

Esta atualizacao acrescenta uma politica **opt-in e por instancia** sem mudar
a politica dos demais jogos por padrao:

```sh
DSM_BACKUP_RETENTION_DAYS=14
DSM_BACKUP_RETENTION_INSTANCE_IDS=cli-000001-minecraft-005,cli-000001-dayz-001
```

Os valores devem ser instalados no ambiente dos processos Controller que
agendam backups e processam as confirmacoes. Nao habilitar antes de
dimensionar o armazenamento e validar a implantacao na homologacao.
Configuracao incompleta ou invalida provoca erro, sem exclusao de backups.

Quando habilitada e `keep_single_operational=true`, a politica:

- mantem **todas as copias concluídas nos ultimos 14 dias**;
- preserva a **ultima copia concluida com caminho e SHA-256 reportados**, mesmo
  se for anterior aos 14 dias;
- retém historicos sem data confiavel e arquivos sem metadados de backup;
- programa exclusoes **somente depois do ACK de um novo backup concluido**
  e contabilizado no Controller, nunca durante uma tentativa falha;
- impede o Agent Linux/Windows de aplicar a antiga exclusao por quantidade,
  mesmo que `retention_count` ainda esteja em 7;
- bloqueia pedidos de exclusao manual feitos pelo cliente/Admin contra a
  ultima copia confirmada, contra backups de menos de 14 dias e contra
  artefatos nao confirmados. A API devolve erro 400 em vez de agendar a
  operacao. Copias antigas podem ser excluidas depois que exista uma nova
  copia confirmada e fora da janela de retencao;
- rejeita novas criacoes antes da escrita caso nao haja espaco de seguranca
  (minimo 8 GiB ou duas vezes o ultimo backup mais 4 GiB).

O SHA-256 do ultimo backup e derivado do artefato pelo Agent quando criado,
mas **o Controller nao verifica novamente o disco**. Um teste periodico real
de restauração continua obrigatorio para aceitar um backup como recuperavel.

## Gate de capacidade (obrigatorio)

No Horizon, em 12/11/2026, havia aproximadamente 37 GiB livres, enquanto os
sete arquivos Minecraft 005 ocupavam ~17 GiB e os sete DayZ ~21 GiB.
Com uma copia por dia, prolongar ambos de 7 para 14 dias requer cerca de
**40 GiB adicionais**, fora a margem operacional e o crescimento dos mundos.
Na ativacao, confirmar que nao existem jobs `delete` pendentes/running
enfileirados antes do opt-in, pois os processos antigos podem ter autorizado
comandos sob a politica anterior. Nao ativar durante jobs de exclusao.

Nao ativar a politica nesse volume sem adicionar capacidade, migrar o destino
para outro disco ou estabelecer destino externo validado. A prechecagem de 8 GiB
do Agent protege apenas contra as proximas criacoes, **nao substitui**
a reserva de capacidade para toda a janela.

## Preflight de capacidade (somente leitura)

Execute antes de habilitar os opt-ins no Controller, diretamente no host de
armazenamento. O comando retorna 0 apenas se houver espaço para completar a
janela de 14 dias no ritmo atual de uma copia diaria por instancia, **mais**
uma copia transitoria por instancia (limpeza somente apos ACK) e 20 GiB
reservados para sistema, jogos e restauracao:

```sh
python3 scripts/backup_age_retention_capacity_gate.py \
  --backup-root /opt/dsm/runtime/hybrid-agent-state/backups \
  --instance cli-000001-minecraft-005 \
  --instance cli-000001-dayz-001 \
  --days 14 --copies-per-day 1 --reserve-gib 20
```

`status=blocked_insufficient_capacity` e codigo 2 **impedem a ativacao**.
A projecao usa o maior arquivo completo encontrado para cada instancia e
supoe que esse tamanho nao cresca; portanto, `pass` e necessario, mas nao
suficiente para autorizar o release. Falha na inspeção ou ausencia de uma
copia-base tambem bloqueia, sem tentar remover cache ou backups.

Protecoes de rollback do Steam Workshop podem manter revisoes fisicas
de conteudo atualmente marcado como `absent`. Nao remover esses caches
automaticamente apenas pela ausencia da atribuicao atual.

## Aceite

Verificar com dados descartaveis: cobertura em 13 e 16 dias; substituicao
falha; ausencia de SHA-256 ou timestamp; falta de espaco; timeout de ACK;
duplicacao de exclusoes; arquivo orfao; efeito em outras instancias; e
restauração do ultimo backup. Nenhuma limpeza de backups de producao ocorre
durante o rollout de código.
