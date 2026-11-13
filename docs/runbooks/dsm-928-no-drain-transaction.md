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
em runner GitHub-hosted e confirma que ambas preservam PID/timestamp.

Adicionalmente, a fixture tests/fixtures/update_928_real_functions_rehearsal.sh
**importa o codigo real de update.sh** e executa suas funcoes
validate_preserved_data, create_backup, create_staging, preserve_data,
validate_staging, apply_update e rollback sobre uma instalacao
**ficticia e pequena** em /tmp, com mundo e estado persistentes de teste.
A fixture de funcoes NAO chama main(); adicionalmente, a fixture
tests/fixtures/update_928_main_path_rehearsal.sh chama o **main() real**
sobre a instalacao de teste, executando as validacoes de versao SemVer, pacote,
disco, backup, staging, apply_update, update_version_file,
update_configuration_version e validate_final_installation. Executa tambem o
caminho real de tratamento de erro e rollback ao injetar falha apos aplicar
os arquivos. O systemctl, banco e handlers de stop/start sao stubs locais.
Os testes comprovam a **ordem de drenagem atual do main()**, nao demonstram
uma atualizacao real de producao sem drenagem nem a compatibilidade de protocolo.
O teste combina o fluxo de arquivos real com duas unidades systemd
descartaveis e injeta falha apos a aplicacao, verificando rollback e PIDs.


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
5. Homologar o fluxo principal main() do proprio update.sh, incluindo
   atualizacao real de services, esquema e Agent, em runner descartavel.
   So depois considerar modo no-drain opt-in.

**Nao ativar no Horizon**: update.sh continua parando os servicos gerenciados
durante a atualizacao. Nenhuma mudanca de producao e autorizada por estes
testes. Armazenamento extra #1049 continua adiado independentemente da #928.


## Compatibilidade Controller/Agent via heartbeat (diagnostico)

O Agent so envia `no_drain_compatibility_probe` quando
`DSM928_COMPAT_DIAGNOSTIC=1`. A mensagem contem `agent_id`,
`request_id` aleatorio de 128 bits, `schema_version=1` e o contrato
`dsm928-readonly-v1`. Nao ha comandos, reinicio ou transicao de estado.

A resposta `no_drain_compatibility_offer` so e emitida depois que
`AgentPairingRepository.authenticate` validou as credenciais.
O Controller usa exclusivamente o `agent_id` autenticado para vincular a
solicitacao, nunca o `agent_id` solto no payload. O Agent confere retorno,
identidade, nonce e contrato exato. Um Controller antigo pode ignorar o probe:
nesse caso o diagnostico local falha fechado e o heartbeat normal prossegue.

`status=wire_compatible` atesta **somente a compatibilidade do envelope
diagnostico**. Nao atesta schema do banco, compatibility do runtime,
processos systemd, rollback, release, versao binaria ou garantia de
continuidade de jogos. Em todas as respostas,
`live_no_drain_authorized=false`. A flag nao pode ser habilitada por
essas mensagens. O updater real continua drenando jogos.

Passos ainda obrigatorios: inventario dos contratos reais Controller/Agent
e suas versões antes/depois, verificador do supervisor no unit systemd de
teste, reinicio independente do Controller mantendo o PID original do game,
rollback apos crash da transacao real, ensaio com pacote distribuivel e
observacoes confiaveis de jogo e persistencia. PR permanece Draft.


## Ensaio Controller HTTP substituto + rollback com supervisor isolado

O teste opt-in `test_controller_http_surrogate_restarts_while_pinned_supervisor_survives_rollback`
em `tests/update_game_uptime_systemd_e2e_test.py` roda somente em runner descartavel,
com `CAPIVARA_DSM928_SYSTEMD_E2E=1`, `root` e nenhuma instancia DSM ativa.

- Inicializa `console_supervisor.py` real a partir de copia versionada SHA-256
  em uma unidade systemd `dsm928-e2e-*.service`; o processo filho e apenas
  `/usr/bin/sleep`, nao uma JVM Minecraft.
- Inicia servidor Python `http.server` transitorio em loopback como
  **substituto do Controller**, sobre arquivos ficticios em `/tmp`.
- Prepara, aplica e reverte arquivos com as funcoes reais de `update.sh`.
  Reinicia o servidor HTTP descartavel entre a aplicacao e o rollback.
- Injeta falha apos a troca e verifica o journal `rolled_back`, o mundo e
  banco ficticios, o mesmo PID e start stamp do supervisor, SHA-256 e
  comunicacao via socket antes e depois.

**Escopo limitado:** nao exercita o Controller DSM real, a negociacao real
entre dois hosts, schema real, JVM Minecraft, arquivo de unit de cliente,
`cap update run` nem o `main()` em modo sem drenagem. O resultado positivo
nao autoriza deploy; `live_no_drain_authorized=false` permanece obrigatorio.


## Recuperacao controlada apos interrupcao abrupta (descartavel)

O metodo `recover_interrupted()` em `game-uptime-transaction.py`
**nao** executa automaticamente durante inicializacao ou nova tentativa.

- Exige `operator_reviewed=True` explicitamente e restringe o workspace a
  subdiretorio de `/tmp` e os processos a `dsm928-e2e-*.service`.
- Aceita apenas journal duravel original nos estados `prepared` ou `applied`,
  com formato, escopo e lista de unidades validos.
- Antes de chamar o callback de rollback, compara unidade, PID, timestamp
  monotonico e estado ativo com os registros anteriores a interrupcao.
- Grava `recovery_started` com fsync **antes** do rollback; em sucesso grava
  `recovered_rollback`. Nao reutiliza o journal nem permite reexecutar o
  rollback apos um resultado terminal.
- Em divergencia de identidade, journal invalido ou falta de revisao, nao
  chama o callback. Se o rollback falha ou ha nova queda abrupta, o journal
  fica em estado de recuperacao manual: **nao e repetido automaticamente**.

Os testes descartaveis incluem processo filho encerrado com SIGKILL apos
alterar um arquivo de teste, bloqueio de replay, rollback revisado, PID
alterado, symlink/journal corrompido e falha durante recuperacao.

**Limitacao:** o callback de rollback e fornecido pelo teste; o codigo
nao sabe recuperar um pacote DSM real. O journal nao e prova contra
manipulacao pelo proprio proprietario/root. Nao e um modo no-drain para
`update.sh main()`, nao cobre migração real de DB, servidor Minecraft
Java nem integracao com plano de controle em producao. Continua bloqueado
para uso em instancias reais.


## HTTP autenticado com persistencia SQLite isolada

O teste `tests/update_game_uptime_sqlite_http_integration_test.py` roda no
CI, sem opt-in e sem acessar o Horizon. Utiliza:

- `AgentPairingRepository` real para emitir credencial e parear um Agent
  ficticio; identidade Controller criada por `RegistryRepository`;
- backend SQLite descartavel e o **dispatcher de heartbeat real**
  `agent_remote_http.dispatch_heartbeat` exposto por listener HTTP
  minimo em `127.0.0.1`; nao importa o servidor web DSM completo;
- primeira negociacao opcional com nonce por heartbeat, armazenamento real
  em `agent_runtime_inventory`, encerramento do listener e da conexao
  backend, reabertura do mesmo banco e segunda negociacao com novo nonce;
- autenticacao invalida e divergencia de identidade entre credencial,
  envelope e payload, mantendo `live_no_drain_authorized=false`;
- preservacao do fluxo de heartbeat legado sem probe opcional.

**Limite de escopo:** o teste comprova persistencia do dispatcher real e da
credencial, mas nao executa `dashboard/server.py` como processo completo,
nao troca binarios reais do Controller, nao cria Agent remoto de verdade,
nao reinicia uma JVM Minecraft e nao autoriza atualizacao sem drenagem.


## Cobertura operacional obrigatoria dos jogos (preflight #928)

O modulo `update-manager/game-uptime-coverage.py`, conectado ao preflight,
recebe a lista **explicita** de unidades de jogo que devem continuar ativas
(`expected_active_units`) e o inventario observado pelo systemd.

- A lista deve incluir ao menos uma instancia Minecraft e uma DayZ para
  esta homologacao multi-jogo; campos ausentes, repetidos ou invalidos bloqueiam.
- Exige conjunto exato de unidades observado (sem unidade ausente ou inesperada),
  `identity_verified=True`, PID maior que 1, timestamp monotonico de inicio
  valido e quantidade do inventario consistente.
- Se o Minecraft estiver parado e o DayZ ativo, reporta
  `expected_active_service_not_running`; nao permite declarar sucesso para
  continuidade do Minecraft.
- Se o baseline esperado nao for fornecido, a cobertura e considerada
  **nao comprovada**; nao infere que a ausencia de processos e estabilidade.
- `no_drain_operational_coverage_verified` significa apenas inventario
  instantaneo elegivel para ensaio **descartavel**, NAO uptime entre
  snapshots nem autorizacao de update. `live_no_drain_authorized=False`
  em todos os caminhos.

Estado operacional observado em 13/11/2026: Node1 disponivel, Agent
2.0.132 ativo e comunicacao TLS com Controller; Horizon 2.0.132 com
DayZ ativo e Minecraft 005 inativo em uma verificacao. A parada do
Minecraft foi registrada pelo systemd as 20:08 (America/Sao_Paulo),
sem causa de comando identificada nesta auditoria. Essa observacao
**nao** e uma homologacao multi-jogo de atualizacao no-drain.
