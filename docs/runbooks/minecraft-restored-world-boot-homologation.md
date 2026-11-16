# Homologacao de boot de mundo restaurado — Minecraft 005 (#1013)

A migracao ATM11 0.13→0.14 e boot da distribuicao oficial 0.14.0-beta,
NeoForge 26.1.2.126, com 291 mods, foram comprovados isoladamente no CI.
Em 12/11, o ultimo backup fisico do Minecraft 005 foi validado por SHA-256
e restaurado com o Agent em sandbox (5.358 arquivos, 2.986.410.210 bytes).
**Ainda falta iniciar o jogo com esse mundo restaurado** para homologar
a recuperacao de ponta a ponta.

## Etapa zero: preflight read-only

O verificador analisa o manifesto inicial do TAR.GZ, identidade de instancia,
disponibilidade de memoria e disco, carga do host, socket TCP local e systemd.
**Nao extrai, inicia, para ou modifica nenhum servidor.** Exige no minimo
12 GiB de memoria efetivamente disponivel e 12 GiB livres de armazenamento
(ou mais, conforme tamanho do backup). Essas margens sao precondicoes,
nao garantia de que o jogo funcionara.

```sh
# Substitua pelo ID de um backup atual, conferido no Controller e no Agent.
# Nao utilize automaticamente o ID historico de outro dia.
BACKUP_ID="<backup-id-verificado>"
BACKUP_ROOT="/opt/dsm/runtime/hybrid-agent-state/backups"
python3 scripts/minecraft_restored_world_boot_preflight.py \
  --archive "$BACKUP_ROOT/cli-000001-minecraft-005/$BACKUP_ID.tar.gz" \
  --sandbox-parent /tmp \
  --instance-id cli-000001-minecraft-005 \
  --backup-id "$BACKUP_ID" \
  --port 25596
```

So prosseguir se `status=preflight_pass` e exit 0; exit 2 significa
**nao iniciar o boot neste host**. A leitura do primeiro manifesto
**nao verifica novamente o SHA-256 do backup**, que deve ser comprovado
separadamente por hash fisico contra os metadados do Controller.

## Homologacao subsequente em host descartavel, preferencialmente Node1

- Node1 esta offline; **nao utilizar Horizon como alternativa automatica**
  quando o preflight bloquear memoria, CPU, portas ou disco.
- Transferir o backup privado apenas por canal autenticado para destino
  descartavel autorizado, verificando SHA-256; nao anexar mundos ou dados
  de jogadores como artefatos de CI publicos.
- Usar o Agent de restauracao sob *root de instancia ficticia*, com
  diretório temporario e estado parado, nunca apontando para um service
  ou um volume de producao. Nao manipular os backups originais.
- Preparar o NeoForge da revisao instalada, com exatamente 291 mods,
  e ajustar somente na **copia descartavel** a escuta para loopback
  `127.0.0.1:25596`, desabilitando RCON/query/portas externas.
- Executar o Java em unit systemd descartavel sem restart automatico,
  usuario nao-root, resource limits (ex.: `MemoryMax=8G`), isolamento
  de rede para loopback, working dir da copia, `KillMode=control-group`.
- Exigir `Done` na janela do log do boot corrente, status ping TCP
  Minecraft 1.21+ respondendo na porta isolada, mods/loader confirmados,
  level.dat do mundo restaurado e desligamento sem corrupcao.
- Comprovar nenhuma alteracao ao mundo e servidor originais, encerrar unit
  e eliminar apenas o workspace descartavel; produzir relatorio com
  sucesso/falha e checksums, sem dados privados.

O preflight de recursos **nao cria a unit, nao executa o jogo e nao
substitui a homologacao posterior**. O gate de release deve continuar
bloqueado ate essa validacao real e ate o armazenamento de 14 dias
passar com margem operacional.


## Resultado atual do preflight e cobertura do gate — 16/11/2026

No Horizon, foi verificado em modo somente leitura o manifesto do backup
`9bab92da-2ce1-47a7-a9cf-515f3f3087a9` do Minecraft 005.
O gate retornou `status=blocked` e `reasons=["insufficient_available_memory"]`:
aproximadamente **6,83 GiB** de `MemAvailable` para o minimo de **12 GiB**
exigidos, com aproximadamente **38,7 GiB** de espaco disponivel no volume.
Nao executar boot ou usar o Horizon como destino de homologacao enquanto a
condicao estiver bloqueada. A memoria e o espaco variam e devem ser novamente
checados no momento do teste.

O gate `scripts/minecraft_serverpack_release_gate.py` registra os casos
`pytest` executados e ignorados a partir do XML JUnit. Quando houver
`coverage.status=partial`, inspecionar `coverage.skipped_cases`; os casos
que exigem opt-in, runner CI, artefato privado ou unidade systemd descartavel
**nao estao homologados**, mesmo se `status=tests_passed`.
Se o XML JUnit estiver ausente ou invalido, o gate retorna
`status=tests_failed` (fail-closed). O campo `release_authorized`
permanece `false` em todas as condicoes.

A ativacao da retencao por 14 dias requer capacidade propria e segue
adiada em #1049; o gate de Server Pack nao ativa essa politica nem certifica
a restauracao de um mundo privado a partir de suites unitarias.
