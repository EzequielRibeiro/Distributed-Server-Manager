# DSM #928 — etapa de transacao de atualizacao sem drenagem

**Estado: experimental, exclusivo de testes descartaveis. Nao habilitado no updater real.**

A PR #1042 contem diagnostico somente leitura do impacto da release e de
dependencias systemd, e agora um nucleo testavel de transacao com checkpoint
duravel (update-manager/game-uptime-transaction.py).

## Contrato implementado (somente E2E isolado)

- Trabalha apenas dentro de um workspace descendente de /tmp, nunca na
  raiz, no diretorio de instalacao ou em diretorios de instancia DSM.
- Aceita apenas unidades temporarias dsm928-e2e-*.service; proibe os
  capivara-instance-*.service de clientes. O teste E2E externo confere
  adicionalmente que o host nao tem DSM instalado nem jogos ativos.
- Antes do primeiro write, coleta os dois PIDs e timestamps monotonicos de
  inicio, exige active e cria checkpoint JSON com fsync de arquivo e pasta.
- Executa callback de alteracao sobre **arquivos descartaveis**, valida os
  mesmos PIDs/timestamps, e registra verified com
  live_no_drain_authorized=false.
- Se uma etapa falhar, chama o callback de compensacao, revalida o processo e
  grava rolled_back. Se o rollback falhar ou um PID mudar, grava
  manual_recovery_required; **nunca declara sucesso**.
- Em queda abrupta (SIGKILL/SystemExit), o checkpoint pendente nao e
  reexecutado. Requer analise manual antes de qualquer tentativa nova.

O job disposable-systemd-rehearsal roda com duas unidades systemd transitorias
em runner GitHub-hosted, repete o processo em aplicacao/rollback simulado e
confirma que ambas preservam PID/timestamp.

## Ainda falta para atualizar sem derrubar jogos

1. Fazer uma **transacao do pacote DSM real**, nao apenas o arquivo de fixture,
   com versao, assinatura, staged payload, backup de arquivos/metadados,
   transicao do codigo e rollback aplicavel tambem apos crash.
2. Demarcar os caminhos que uma release pode substituir sem prejudicar
   processos ja executados, especialmente o console_supervisor.py do Minecraft.
3. Demonstrar compatibilidade do protocolo Controller/Agent e da rotina de
   reconciliacao; excluir alteracoes de systemd, runtime e schema inseguras.
4. Exigir snapshot completo de instancias e verificar que *nenhuma* unidade
   ativa foi esquecida. Incluir verificacao de estado apos update e rollback.
5. Homologar o proprio update.sh, nao somente callback da fixture, com
   dois servicos descartaveis. So depois considerar modo no-drain opt-in.

**Nao ativar no Horizon**: update.sh continua parando os servicos gerenciados
durante a atualizacao. Nenhuma mudanca de producao e autorizada por estes
testes. Armazenamento extra #1049 continua adiado independentemente da #928.
