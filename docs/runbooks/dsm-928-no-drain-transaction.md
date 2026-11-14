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


## Ensaio multi-jogo descartavel com verificacao de responsividade

O teste opt-in `test_minecraft_supervisor_and_dayz_udp_standin_survive_apply_and_rollback`
na suite systemd cria dois servicos temporarios `dsm928-e2e-*.service`:
um `console_supervisor.py` real carregado da copia de SHA-256 imutavel
por politica, com filho `/usr/bin/sleep` **em vez de Minecraft Java**;
e um processo Python UDP de consulta-resposta **em vez do servidor DayZ**.

Confere em ambos os servicos o PID e timestamp monotono do inicio,
socket Unix do supervisor e consulta UDP responsiva, antes e depois da
aplicacao dos arquivos ficticios. Exercita tanto sucesso quanto falha
injetada apos o apply, e confirma rollback, mundo e banco ficticios
preservados. Cada operação de arquivos usa as funcoes reais de
`update.sh` executadas em instalacao descartavel em `/tmp`.

**Resultado positivo nao representa homologacao de Minecraft/DayZ reais.**
A JVM Minecraft, o executavel DayZ, os adaptadores reais, a migracao
de banco, o Controller completo e um modo `main()` sem drenagem
continuam sem essa prova. `live_no_drain_authorized=false`.


## Pré-visualização de unidade systemd com supervisor versionado

`agents/linux/runtime/materializers/systemd.py` agora aceita
`render_unit(spec, pinned_supervisor_preview=...)` **somente para
gerar texto**, usando o materializador nativo e um supervisor previamente
estagiado por SHA-256. Esse parâmetro não é lido de um campo da
especificação da instância, nem utilizado por
`SystemdMaterializer.apply()` ou `inspect()`.

A validação da proposta exige nome `console-supervisor-<sha256>.py`,
hash exato, arquivo regular sem symlink nem hardlinks adicionais,
permissão sem escrita, diretório não gravável por outros usuários e
caminho fora de `/opt/dsm` e `/opt/capivara-agent`.
`tests/update_game_uptime_supervisor_materialization_test.py` cobre
renderização, integridade, divergências e manutenção do comportamento
legado.

**Atenção:** isto **não instala ou altera** unidade systemd existente,
não faz daemon-reload, não garante permissão de leitura para o usuário
de serviço, não migra um processo em execução e não conecta o modo
no-drain ao `update.sh`. A execução isolada com unidade real, a
provisão permanente do diretório versionado, a compatibilidade de
usuários/grupos e a manutenção das versões antigas até o último PID
encerrar precisam ser verificadas antes de sequer considerar ativação.
O update de produção ainda drena jogos.


## Identidade Unix e leitura do supervisor no systemd descartavel

A pré-visualização `render_unit(spec, pinned_supervisor_preview=...)`
valida tambem o usuario systemd declarado no `spec["user"]`.
O teste estático exige que a conta exista, que **cada diretório ancestral**
possa ser atravessado e que o arquivo SHA-256 seja legivel pela propria
identidade Unix, considerando UID, grupo primario e grupos suplementares.
O teste falha fechado para usuário inexistente, `/tmp` temporário com
permissão 0700 sem acesso por essa conta, arquivo não legível, symlink,
arquivo alterado ou diretorio inseguro.

O E2E `test_pinned_minecraft_supervisor_runs_as_unprivileged_systemd_user`
sobe uma unidade `dsm928-e2e-*.service` temporária via `systemd-run`
com `User=nobody` e `NoNewPrivileges=yes`, verificada em
`/proc/<MainPID>/status`. O supervisor Python versionado real executa
um filho **`sleep`**, com socket Unix próprio restrito ao usuário
descartável. Antes e depois da aplicação e rollback de arquivos
fictícios em `/tmp`, o teste verifica PID, timestamp e resposta do
socket. O teste somente roda em runner Linux com root, opt-in e guarda
que recusa instalação DSM ou unidades de jogo vivas.

**Limites:** validação de bits POSIX não substitui checagens de ACL,
SELinux/AppArmor, mount namespaces ou acessibilidade do diretório
persistente de destino. O teste não utiliza o usuário real de clientes,
nem substitui a unidade `capivara-instance-*.service`, nem executa uma
JVM Minecraft. Ainda são necessárias provisão permanente root-owned,
retencao de versoes antigas, rollback do pacote completo e validação
operacional no updater. `live_no_drain_authorized=false`; release
permanece bloqueado.


## Retencao de supervisores e plano reversivel de unidade (somente leitura)

O modulo `update-manager/game-uptime-supervisor-retention.py` registra
referencias explicitas do `ExecStart` das unidades instaladas e dos
processos em execucao (unidade, PID, timestamp monotônico e caminho do
supervisor informado pelo observador). Exige inventario completo, nomes
de unidades validos, arquivos versionados regulares com hash correto
e sem permissao de escrita. Uma divergencia impede classificar as
versoes nao referenciadas.

Quando o processo ativo ainda utiliza SHA antigo e a unidade instalada
ja aponta para o SHA novo, **ambos permanecem protegidos**. Todas as
versoes validas continuam preservadas, inclusive as aparentemente nao
referenciadas. A lista `manual_review_only_unreferenced_versions`
serve apenas para investigacao. **Nao existe exclusao automatica**:
`automatic_deletion_allowed=false` em todos os retornos.

O metodo `SystemdMaterializer.plan_pinned_transition()` adiciona uma
ponte com o materializador nativo: valida um arquivo de unidade existente
de propriedade Capivara, exige o SHA-256 do baseline fornecido pelo
operador, confere o usuario/permissoes do supervisor pinado e calcula
o SHA-256 da unidade proposta. Recusa baseline defasado, unidades
estranhas e symlink. **Nao grava nenhum arquivo nem chama systemctl.**
A unidade anterior precisa ser preservada fora do metodo e todas as
identidades de processo precisam ser rechecadas antes e depois de
qualquer futura substituicao. Isso nao implementa a substituicao
transacional e tampouco sua reversao real.

Limites: as referencias informadas pelo chamador nao sao prova suficiente
de controle de processos; faltam verificacao de execucao/cgroup do
systemd no host efetivo, configuracao persistente do diretorio,
integracao de troca/rollback no updater e homologacao com jogos reais.
O release continua bloqueado e `live_no_drain_authorized=false`.


## Transacao de arquivo systemd real, limitada a fixture em runner descartavel

O modulo `update-manager/game-uptime-systemd-swap.py` e um
**prototipo isolado**, nao um modo de atualizacao do DSM. Somente
unidades `dsm928-e2e-*.service` marcadas com identificador exato e
`ExecStart=/usr/bin/sleep` sao elegiveis. O conteudo fica limitado a
sete linhas previamente permitidas. Nomes `capivara-instance-*`,
`dsm-dashboard` e outras unidades reais sao recusados.

Com o opt-in `CAPIVARA_DSM928_SYSTEMD_E2E=1`, root, um host sem DSM
instalado nem instancias de jogo ativas, o runner de CI pode gravar
**somente** a fixture com nome `dsm928-e2e-*` em
`/run/systemd/system`. Nenhum host de producao e elegivel.
Testes unitarios podem usar uma arvore privada em `/tmp` com
`daemon-reload` inteiramente simulado.

A troca exige hash SHA-256 exato da unidade original, preserva copia
duravel de seus bytes e journal com fsync *antes* da substituicao
atomica, executa `systemctl daemon-reload` e verifica novamente
PID, timestamp monotônico e bytes da unidade. Se houver falha
capturada, reverte a unidade e registra `rolled_back`. No sucesso,
o operador deve solicitar expressamente `restore_unit(...,
operator_reviewed=True)` para restaurar a copia antiga. Journal
`prepared` apos queda abrupta pode ser revisado e restaurado;
estados finais ou falha na propria recuperacao nao permitem replay.

O E2E adiciona uma unidade `sleep` descartavel em
`/run/systemd/system`, troca o arquivo enquanto o processo
permanece ativo, confere o mesmo PID, restaura e remove a fixture.
O resultado **nao** equivale a atualizar unit de Minecraft, DayZ,
Controller ou Agent, nao substitui o adaptador/materializador de
producao, nao valida jogos reais e nao executa `update.sh`
sem drenagem. `live_no_drain_authorized=false` continua absoluto.


## Ensaio com supervisor Minecraft real versionado e troca systemd reversivel

O modulo de **ensaio descartavel** `game-uptime-systemd-swap.py`
tambem aceita, em sua allowlist de 7 linhas de unit, uma unica
forma especifica de `ExecStart`: o Python do sistema executando o
`console_supervisor.py` autentico identificado por SHA-256, dentro
de `<journal>/versions/console-supervisor-<sha>.py`, apontando
exatamente para `<journal>/console.sock` e rodando **apenas**
`/usr/bin/sleep` com tempo limitado como processo filho.
O arquivo e o diretorio versionado devem ser regulares, com ownership
do usuario do teste, sem permissao de escrita para terceiros,
sem symlinks, com nome e hash conferidos. Uma copia adulterada,
caminho de socket alternativo, caminho substituivel do DSM ou
comando arbitrario bloqueia a transacao antes da escrita de unidade.

O teste de unidade `test_pinned_real_supervisor_files_swap_and_restore_in_private_fixture`
estagia a versao original do supervisor e uma segunda revisao
descartavel com comentario inofensivo, ambas por SHA-256, e
verifica a aplicacao e o retorno para a versao antiga.
O ensaio com systemd real, em runner CI root descartavel,
`test_actual_pinned_minecraft_supervisor_unit_swap_retains_old_live_revision`,
inicia a unidade temporaria `dsm928-e2e-*.service` com a revisao
original, coleta PID e start stamp, consulta seu socket, substitui a
unidade instalada pelo caminho da segunda revisao com
`systemctl daemon-reload` e comprova que o processo em execucao
continua usando **a revisao original**. Depois restaura o arquivo
de unidade e confirma que ambas as revisoes SHA continuam
disponiveis. A fixture systemd e removida ao final.

A alteracao da unidade nao migra o processo em execucao para
um supervisor novo, apenas define qual arquivo seria utilizado
em uma **futura** inicializacao. Essa observacao evita confundir
continuidade atual com migracao de processo.

**Fora do escopo:** nao existe autorizacao para usar esta rotina
em nomes de unidades Capivara, no materializador de producao,
no Controller ou Agent do host real. Nao ha JVM Minecraft nem DayZ
neste ensaio; nao se exercita o update do DSM sem drenagem.
`live_no_drain_authorized=false`; PR continua Draft.


## Composicao isolada: atualizador de arquivos + supervisor pinado + rollback

O modulo `update-manager/game-uptime-isolated-compose.py` compoe
**apenas em uma fixture previamente identificada dentro de /tmp** a
preparacao do backup, a aplicacao das funcoes reais de arquivos do
`update.sh` (via harness descartavel), a troca de uma unidade
`dsm928-e2e-*.service` e a verificacao de continuidade de processos.
Ele utiliza o journal duravel de `game-uptime-transaction.py` e
exige inventario de unidades isoladas, sem aceitar nomes Capivara de
producao. Nao invoca o `update.sh main()`.

A composicao registra `prepared` antes da aplicacao e valida PIDs e
start stamps durante a transacao. Quando uma falha capturada ocorre,
tenta **ambas** as compensacoes: primeiro a restauracao da unidade e
depois o rollback dos arquivos, verificando novamente os processos e
marcando `rolled_back` em sucesso. Se alguma compensacao falhar,
deixa `manual_recovery_required` e bloqueia replay automatico.
Uma interrupcao abrupta do processo requer revisao operacional dos
journals de ambos os componentes. O estado `verified` de uma aplicacao
bem-sucedida nao implica autorizacao para producao.

Os testes unitarios `tests/update_game_uptime_isolated_compose_test.py`
cobrem: sucesso, falha apos troca da unidade, falha antes da troca,
rollback parcial, erro de saude e recusa de inventario invalido.

O E2E opt-in `test_integrated_disposable_updater_and_pinned_unit_swap_preserve_two_pids`
instala em um runner isolado duas unidades de teste: um supervisor
Minecraft **Python real identificado por SHA-256** cujo filho e
`/usr/bin/sleep`, e um substituto UDP para DayZ. Testa os cenarios
de aplicacao bem-sucedida e falha injetada apos o update de arquivos
e a troca systemd. Valida em ambos os casos o mesmo PID/start stamp,
o socket do supervisor, a consulta UDP, o mundo e banco ficticios, as
versoes antigas e o journal. No cenario de sucesso, a unidade e o
produto de fixture sao restaurados explicitamente antes do teardown.

**Pendencias para liberar no-drain real:** integrar o plano
Controller/Agent ao atualizador, provar uma atualizacao real sem
interromper Minecraft/DayZ e sem troca de seus PIDs, exercitar rollback
de banco e migracoes reais, dar suporte a crash/recovery do fluxo
completo e revisar flags operacionais. Nenhuma chamada ao updater
de producao e nenhuma alteracao em servidores reais foram efetuadas.
`live_no_drain_authorized=false` permanece incondicional.


## Recuperacao da transacao composta apos encerramento abrupto

`update-manager/game-uptime-isolated-compose.py` agora oferece
`recover_interrupted()`, **apenas para uma fixture autenticada em
`/tmp`** com journal anterior em estado `prepared` ou `applied`.
A recuperacao nunca roda automaticamente e exige
`operator_reviewed=True` apos inspeção dos journals/arquivos.

Antes de qualquer tentativa, a rotina verifica o marcador original
da fixture, nomes estritamente `dsm928-e2e-*.service`, journal
composto privado e único arquivo de backup não vazio do updater.
Se existir journal de swap em `<fixture>/dsm928-unit-swap.json`,
valida escopo, unidade e status. Um swap `prepared`/`applied`
precisa ser restaurado; swap já `restored`/`rolled_back`
não deve ser repetido. Journal de swap inválido, corrupto,
`recovery_started` ou `manual_recovery_required` bloqueia
a operação. O protótipo exige journal de unidade na própria
fixture, não recupera journals externos nem unidades reais.

Usa o protocolo de `game-uptime-transaction.recover_interrupted`
para comparar o PID e o timestamp monotônico originais com os
processos atuais, gravar `recovery_started` e depois tentar
as duas compensações: restauração de unidade (quando aplicável)
e rollback dos arquivos. O erro numa etapa não impede a tentativa
da outra. Sucesso escreve `recovered_rollback` com fsync.
Falha parcial escreve `manual_recovery_required` e bloqueia
repetição automática ou nova tentativa pelo mesmo caminho.

Em `tests/update_game_uptime_isolated_compose_test.py` foi
executado **SIGKILL de um processo filho real** após a
aplicação das funções reais de arquivo do updater em árvore
fictícia e a troca de unidade em diretório privado com
`daemon-reload` simulado. O teste comprova journal
`prepared`, recusa de replay, recuperação revisada da
unidade e dos arquivos, world e banco fictícios preservados.
Também testa falha antes do swap, PID alterado, journal
corrompido e recuperação parcialmente malsucedida.
O ensaio systemd real anterior permanece separado deste
teste de SIGKILL: não se afirma que o Linux systemd
real tenha sido interrompido à força nesta etapa.

**Restrições:** continua sem integração ao updater em modo
`main()`, Controller/Agent em ciclo completo, migrações
reais de bancos, JVM Minecraft ou executável DayZ. A
prova é de recuperação de uma fixture, não de atualização
sem drenagem de servidores reais. Nenhum serviço de
produção foi modificado. `live_no_drain_authorized=false`.


## Integracao do dispatcher Controller/Agent no ensaio systemd isolado

O E2E `test_integrated_disposable_updater_and_pinned_unit_swap_preserve_two_pids`
executa agora, no mesmo ensaio do runner descartavel, o dispatcher real
`agent_remote_http.dispatch_heartbeat`, autenticação real
`AgentPairingRepository` e persistencia SQLite do Controller.
A comunicacao utiliza um servidor HTTP fino em `127.0.0.1`, e o
Agent utiliza `game_uptime_agent_wire.build_probe` e
`verify_offer`, ambos reais, para validar o contrato e o nonce.

Antes, durante e depois das operacoes sobre a fixture, o teste verifica
heartbeats autenticados, inventario persistente do Agent no SQLite,
`health_status=online` e `live_no_drain_authorized=false`.
Apos a troca da unidade de supervisor de teste, o endpoint HTTP
e o backend SQLite do Controller sao encerrados e reabertos no mesmo
arquivo de banco. Novas credenciais autenticam corretamente,
nonce antigo nao valida uma oferta nova e um segredo incorreto recebe
HTTP 401 sem oferta de compatibilidade. O mesmo exercicio ocorre
durante restauracao dos componentes em ambos os cenarios: sucesso e
falha injetada apos aplicacao da fixture.

Em paralelo, a unidade temporaria do supervisor Minecraft com filho
`sleep` e a unidade temporaria DayZ UDP preservam PID/start stamp e
continuam respondendo a sondagens. As funcoes de update de arquivo
utilizam somente a fixture `/tmp`. O teste roda exclusivamente no
CI opt-in com systemd e foi executado com resultado `ok`.

**Limite importante:** reiniciar o listener temporario e reabrir o
backend SQLite **nao e reiniciar o Controller DSM completo**, nem
constitui migracao de banco real ou teste da rotina de heartbeat de
um Agent daemon real. Da mesma forma, `sleep` e o stand-in UDP
**nao sao os executaveis Minecraft/DayZ**. Nao existe
`update.sh main()` no-drain integrado. A evidência é
diagnostica e exclusivamente de laboratorio. O modo
`live_no_drain_authorized=false` e o bloqueio de release
permanecem obrigatorios.
