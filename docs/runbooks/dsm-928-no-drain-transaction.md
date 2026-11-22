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


## Sincronizacao com main e roteamento real de heartbeat (14/11/2026)

A PR foi sincronizada via merge commit com `main` depois que o
GitHub apontou conflito em `agents/linux/runtime/agent.py`.
A reconciliacao preserva conjuntamente a geolocalizacao do Agent
(`observe_host_geolocation`), o recebimento persistente da
`controller_location` e os campos de diagnostico
`no_drain_compatibility_probe`/`no_drain_wire_diagnostic`.
O teste estrutural `test_merged_agent_location_and_no_drain_diagnostics_coexist`
verifica que as observacoes de geolocalizacao e a troca de contrato
diagnostico sobrevivem a futuras atualizacoes da branch.

O teste `test_actual_controller_part11_post_route_with_durable_agent_credential`,
na suite `update_game_uptime_sqlite_http_integration_test.py`,
executa o corpo real de `server_part11.integrated_post` (extraido
da AST Python para nao importar nem inicializar o dashboard completo)
como metodo `do_POST` em um listener descartavel `127.0.0.1`.
O despacho autentica credenciais reais de
`AgentPairingRepository` e atualiza o banco SQLite temporario.
O teste inclui verificacao de nonce do Agent, HTTP 401 para segredo
invalido e reinicio da rota HTTP reabrindo o mesmo banco de dados.
A compatibilidade continua meramente diagnostica.

**Limite importante:** a execucao da funcao de rota dentro de um
handler minimo nao equivale a subir a aplicacao completa de
Controller e sua cadeia de patching/middleware/instalacao,
nem ao reinicio do processo Agent real. Nao autoriza qualquer
acao de atualizacao em hosts de producao:
`live_no_drain_authorized=false`, PR Draft, release bloqueado.


## Heartbeat do Linux Agent real em dois processos Python isolados

A suite `tests/update_game_uptime_agent_runtime_restart_test.py`
inicia **dois interpretadores Python independentes** e importa o
modulo real `agents/linux/runtime/agent.py`. Cada processo le a
configuracao efetiva de teste por `CAPIVARA_AGENT_CONFIG` e executa
`heartbeat()`, incluindo o transporte real `urllib` em `_post()`
e a validacao `verify_no_drain_offer()`.

O teste cria credenciais permanentes na base SQLite temporaria do
Controller e comunica-se com a implementacao real
`agent_remote_http.dispatch_heartbeat` via um HTTP loopback.
Apos o primeiro heartbeat, reinicia o listener e reabre o banco:
outro **processo Agent** usa as mesmas credenciais duraveis, confirma
resposta `online` e `wire_compatible`, sem autorizar no-drain.
Um terceiro caso exercita payload legado sem probe, e uma credencial
invalida falha com 401. O diretorio de estado e a configuracao do
Agent sao privados e temporarios; o teste impede que uma oferta de
comando de jogo, update ou provisionamento produza efeitos reais.

Para evitar inventariar host ou instancias do runner, apenas
`_inventory()` e caminhos de ativacao de comandos foram bloqueados
ou substituidos pela fixture. A funcao real `heartbeat()`, a
importacao integral do modulo de runtime Linux Agent, seu cliente
HTTP real e o verificador de compatibilidade **sao exercitados**.

**Limites:** isto nao inicia `agent.run_forever()`, nao executa
reconciliacao real, nao inicia o Controller completo, nao valida TLS
de producao e nao migra banco de cliente. Os testes de jogos
continuam com filho `sleep` e stand-in UDP em CI separado.
`live_no_drain_authorized=false`; merge e release bloqueados.


## Diagnóstico read-only a partir do updater (14/11/2026)

A opção `--no-drain-report /caminho/release-candidata` em `update.sh`
executa apenas o `update-manager/game-uptime-preflight.py` **do checkout
do updater** (nunca do pacote candidato), antes de exigir root, gerar logs,
criar backups, interromper serviços ou substituir arquivos. Ela lê inventário
systemd e compara árvores de arquivos, retornando JSON com a classificação,
impacto, cobertura e motivos de bloqueio. O código de saída **2 é
intencional**, mesmo para um relatório gerado com sucesso.

Não é uma etapa de homologação real nem autoriza no-drain: a opção
`--no-drain` segue rejeitada e `live_no_drain_authorized=false`.
O relatório CLI padrão não obtém um contrato Controller/Agent autenticado
nem evidencia automaticamente supervisor Minecraft versionado; essas
verificações continuam bloqueantes para um upgrade sem drenagem.
A análise pode envolver leitura extensa dos arquivos da instalação, mas
não precisa e não deve executar o atualizador.


## Gate de compatibilidade no ensaio composto descartável

`game-uptime-isolated-compose.py` agora expõe
`execute_with_compatibility_gate(...)`, um ponto de entrada que valida
**antes de qualquer backup ou apply** um contrato sintético
Controller/Agent com `game-uptime-compatibility.assess()`, o código
de `console_supervisor.py` no pacote instalado e no candidato e a
afirmação de pinagem de supervisor da fixture. Contratos incompatíveis,
sem campos obrigatórios, supervisor ausente ou não pinado são rejeitados
sem criar journal nem modificar a instalação de ensaio.

Os testes verificam a falha sem efeitos colaterais e o sucesso com
composição real dos callbacks de atualização, troca de unidade simulada
e rollback, incluindo candidato que altera o código do supervisor mas
preserva a versão antiga em execução no ensaio. O comprovante identifica
`compatibility_source=synthetic_disposable_fixture` e sempre retorna
`live_no_drain_authorized=false`.

**Limite:** o booleano de pinagem e os contratos são entradas de fixture,
**não** prova autenticada de negociação Controller/Agent nem pinagem
operacional em produção. Não há caminho de autorização no updater real.
Ainda faltam negociação autenticada do release alvo, evidência de pinagem
do processo real, transação integrada no `update.sh main()`, rollback de
banco e homologação de continuidade Minecraft/DayZ em host isolado.

## Ensaio com evidências do heartbeat e pinagem (14/11/2026)

O módulo `update-manager/game-uptime-evidence-rehearsal.py` conecta
o protocolo existente do heartbeat (`build_probe`,
`assess_authenticated_probe`, `verify_offer`) ao verificador read-only
do SHA-256 e do `ExecStart` de um supervisor pinado. O ensaio compara
o PID e o start stamp declarados para a unidade simulada com a
observação do supervisor **antes e depois** da transação composta;
a gravação de journal e o preparo dos arquivos só ocorrem após a
verificação inicial.

O teste rejeita replay de nonce, identidade divergente, oferta com
campos/ações inesperadas, unidade ou Agent fora do padrão descartável,
caminho de supervisor fora do workspace privado, SHA adulterado e
identidade do processo alterada.

**Evidência ainda sintética:** a identidade autenticada é fornecida
pela fixture, assim como a inspeção systemd. Nenhuma credencial real
é utilizada, nenhum Agent/Controller real foi atualizado e não se
estabeleceu prova autenticada de pinagem em produção. A saída é
sempre `live_no_drain_authorized=false`. O código não é chamado
por `update.sh main()` e não altera o gate de release.

## Integração HTTP autenticada do ensaio (14/11/2026)

`tests/update_game_uptime_authenticated_http_transaction_test.py` combina
uma fixture de pareamento real em SQLite com o dispatcher real
`dispatch_heartbeat` sobre um listener HTTP efêmero (`127.0.0.1`).
O Agent sintético apresenta credencial emitida e cadastrada no banco
isolado; a resposta do Controller atravessa a API antes de ser entregue ao
verificador de envelope, SHA-256 e PID do ensaio descartável. As provas
negativas incluem credencial incorreta (401, sem offer), identidade do
Agent divergente, resposta anterior após reiniciar o Controller com novo
nonce e PID do supervisor diferente da observação prévia. A transação
não cria snapshot se qualquer uma dessas condições falha.

Este teste avança a autenticação do transporte: **não** autentica o
Controller de produção, não verifica TLS real, nem prova a pinagem do
supervisor nos cgroups do host. A leitura de systemd e os jogos continuam
simulados. O recibo da fixture continua com
`live_no_drain_authorized=false`, sem integração ao `update.sh main()`.

## Política de testes consolidada da #928 (21/11/2026)

**Objetivo:** parar de abrir PRs individuais apenas para novos ensaios sintéticos.
A homologação de no-drain continua **bloqueada até evidência operacional**
e passa a usar quatro grupos de aceite, sem inflar indefinidamente a suíte:

1. **Segurança do preflight:** mudanças incompatíveis, identidade, dependências,
   credenciais e versão desconhecida bloqueiam o modo sem drenagem.
2. **Controller + Agent:** rota HTTP integrada real, credencial autenticada,
   reconexão após reinício e diagnóstico somente de leitura.
3. **Transação:** sucesso e falha/rollback dos arquivos, journal persistente,
   dados preservados e duas unidades-jogo com PID/start stamp inalterados.
4. **Supervisor e continuidade operacional:** ciclo real `worker.sh`,
   reinício do grupo, além da pendência de `Agent.run_forever()` e Workers
   operacionais com reconciliação isolada. O ensaio com nove filhos `sleep`
   verifica somente a lógica do supervisor, **não** homologa os daemons reais.

**Execução escalonada em CI (sem remover testes):**

| Alteração | Pré-validação | Ensaio systemd |
| --- | --- | --- |
| Runtime, sistema, updater, workflow, fixture ou caminho não reconhecido | Suíte completa de testes #928 | Todos os ensaios systemd |
| Apenas arquivos de testes #928 | Núcleo fail-closed + cada arquivo modificado, sem repetir módulo | Três cenários decisivos; suíte completa se mudar o próprio E2E ou qualquer dependência relevante |
| Apenas esta documentação | Núcleo de segurança e preflight | Dispensado |
| Push na `main` ou disparo manual | **Suíte completa de testes #928** | **Todos os ensaios systemd** |

As deleções/renomeações de testes obrigam **suíte completa** em vez de
reduzir cobertura inadvertidamente. O workflow `game-uptime-preflight-diagnostics.yml`
mantém `tests/update_preflight_test.sh` em todos os casos e a proteção
`update_game_uptime_discovery_test.py` contra IDs de teste duplicados.
**Nenhum teste anterior foi excluído nem desabilitado na `main`.**

**Regra de encerramento do ciclo:** não criar outro teste para demonstrar
novamente PID, rollback ou handshake já comprovados. Abrir prova nova
**somente para uma lacuna operacional distinta** ou falha reproduzida.
A próxima evidência realmente diferente é a execução segura de
`Agent.run_forever()` e dos daemons Worker operacionais em clone isolado;
enquanto ela não existir, registrar como **pendência**, não substituir por
mais simulações equivalentes.

Esta otimização **não** libera `update.sh --no-drain` em produção.
`live_no_drain_authorized=false`; issue #928 permanece aberta,
PR de release #1096 Draft e jogos reais não podem sofrer interrupção
sem janela de manutenção aprovada.

## Bloqueio de reconciliação local — etapa de implementação (21/11/2026)

O leitor de manutenção `agents/linux/runtime/game_uptime_maintenance_hold.py`
é um **componente real de runtime** compartilhado pelos laços do Agent Linux
(`run_forever()`) e do Worker Hybrid (`heartbeat_cycle()`). Por padrão, se
não existir `/run/capivara-dsm/no-drain-maintenance.json`, o comportamento
anterior é preservado sem qualquer pausa.

Quando o arquivo estiver presente, o leitor aceita apenas um **arquivo
regular, não-symlink, root-owned, sem escrita de grupo/outros, em diretório
root-owned protegido**, com JSON compacto (`kind`, `schema_version=1`,
`transaction_id` com 32 hex, `issued_at`, `expires_at` até 15 minutos).
A presença de conteúdo danificado, diretório inseguro, troca de inode,
data inválida ou expiração **também suspende** os laços abrangidos:
a retomada exige remoção/reconciliação por operador e não é automática.
O leitor é **somente leitura**; não gera, modifica nem apaga o marcador.

O Agent verifica antes dos hooks de startup e em cada volta do agendador:
durante o hold não realiza sua iteração de reconciliação nem a chamada
regular de heartbeat que poderia despachar comandos. O Worker Hybrid
verifica antes da reconciliação local e dos ciclos mutáveis de
configuração, conteúdo, game-data, provisionamento ou backup. Nenhum
dos dois aciona comandos de atualização por causa do marcador.

**Limites obrigatórios:** ainda NÃO existe escritor/controle de ciclo de vida
transacional deste arquivo, ACK autenticado em todas as máquinas ou barreira
para os outros oito processos de `worker.sh`, threads de console/streaming,
comandos externos e Agent remoto em outro host. Logo, a presença do marcador
**não é evidência suficiente de que todos os mutadores foram pausados**.
É proibido criar esse arquivo manualmente como tentativa de habilitar
uma atualização: ele pode suspender operações de clientes sem proporcionar
a segurança necessária. O `update.sh --no-drain` segue read-only/exit 2,
`live_no_drain_authorized=false`.

**Próximo trabalho de implementação**, não novo ensaio sintético:
coordenar uma barreira com confirmação autenticada de todos os Agents e
Workers mutadores, dono transacional durável/rollback e remocao verificável
do hold; só então ligar o caminho de aplicação da atualização sem drenagem.

## Cobertura de todos os nove Workers do supervisor — fase de implementação (21/11/2026)

O `dashboard/workers/worker.sh` inicia nove processos. Agora **todos os nove
verificam o mesmo hold local protegido** antes de iniciar trabalho novo:

- `scheduler_worker.sh`: consulta o leitor Python somente leitura antes de
  gravar o estado; leitor ausente/inseguro bloqueia o tick.
- `automation_worker.py`, `content_update_worker.py`,
  `maintenance_worker.py`, `observability_retention_worker.py`,
  `content_upload_retention_worker.py`,
  `database_intelligence_worker.py`: consultam `maintenance_paused()`
  antes de inicializar repositórios e a cada passagem de seus loops.
- `hybrid_customer_workspace_worker.py`: mesma verificação do loop e
  proteção antecipada de `workspace_cycle()`, inclusive modo `once`.
- `hybrid_agent_worker.py`: já consultava o hold antes da reconciliação e
  antes de abrir banco, conforme etapa anterior.

A função compartilhada `maintenance_hold_gate.py` **reutiliza o mesmo leitor
de `agents/linux/runtime/game_uptime_maintenance_hold.py`**: nenhum segundo
formato, arquivo, flag de ambiente ou novo mecanismo de autorização.
O leitor também tem um **modo de processo somente leitura** para o
`scheduler_worker.sh`: exit 0 sem hold, exit 2 quando presente/inseguro.
Um único teste de regressão agrupado confere o contrato dos oito
entrypoints e a barreira antes do workspace.

**Risco restante:**
- A checagem ocorre **entre ciclos**, não interrompe uma chamada mutadora
  já iniciada. Um loop que está executando um update, expiração de arquivos
  ou shutdown pode continuar apesar de o hold ter surgido; não existe ACK
  de quiescência, contador de operações ativas nem um fencing transacional.
- O Controller HTTP, os Agents remotos, streaming/threads, unidades de
  materialização e executores privilegiados **não estão abrangidos**
  pelo hold local. O supervisor continua reiniciando filhos conforme
  política de produção; o bloqueio é feito em cada filho, não via SIGSTOP.
- Não há coordenador que crie/remova este arquivo com journal durável.
  Não criar manualmente o marcador em hosts com clientes ativos.

**Regra de saída:** somente quando um proprietário transacional obtiver
ACK autenticado de todos os mutadores, verificar fim de operações em voo,
preservar PIDs, executar update/rollback e provar recuperação integral, a
opção pública poderá ser considerada. Até então `--no-drain`
permanece read-only/exit 2 e `live_no_drain_authorized=false`.

## In-flight no Worker de manutenção — evidência local inicial (21/11/2026)

O `maintenance_worker.py` agora envolve cada `tick()` em
`tracked_operation("maintenance_worker", root=ROOT)`. A seção crítica usa
`fcntl.flock(LOCK_EX)` até o retorno completo do ciclo, inclusive comandos
de manutenção, parada/início DayZ e alterações de conteúdo. Dentro da trava,
o Worker **relê o hold root-owned** e só executa quando não existe.
Se a trava não puder ser criada/aberta de modo seguro, o ciclo falha
antes de executar operações de clientes.

**Histórico da PR #1119:** o arquivo de lock era criado em
`dashboard/state/dsm928-worker-operations`, um diretório privado sob a
árvore da instalação. Esse caminho foi substituído pela etapa de travas
fixas em `/run` descrita ao final deste runbook. O método `inspect_operation("maintenance_worker", root=...)`
é **somente leitura**: distingue `operation_in_flight` de
`lock_free_process_identity_unverified` e `unverified`; sempre devolve
`live_no_drain_authorized=false`. Lock livre sozinho nunca demonstra que
existe um Worker vivo, que não há jobs externos já despachados, nem que
o Controller/Agent remoto foi drenado de operações.

A trava é compatível com uma futura barreira: o coordenador precisará
reter locks de **todos os mutadores**, instalar o hold root-owned sob
coordenação atômica, confirmar identidade e término de trabalhos enviados
aos Agents, manter o fence durante atualização e rollback, e somente
então permitir recuperação. Esse coordenador ainda NÃO existe.
Os outros Workers e o Agent Linux ainda não produzem evidências
individualizadas de operação em voo nesta etapa; a #928 continua aberta.

## Testemunho de operações em voo nos nove Workers locais (21/11/2026)

A implementação de `tracked_operation()` da etapa anterior agora cobre **todos
os nove Workers filhos de `dashboard/workers/worker.sh`**, não apenas a
manutenção:

- Automação, atualização de conteúdo, retenção de observabilidade,
  retenção de uploads e inteligência de banco mantêm `flock` durante
  a passagem completa de trabalho; o lock é solto somente após a conclusão
  do ciclo ou do tratamento de exceção. O Worker de manutenção conserva
  a proteção já homologada.
- O Worker Hybrid mantém o lock ao executar `heartbeat_cycle()`, incluindo
  reconciliação e processamento de comandos; o Workspace Hybrid o mantém
  durante os comandos de arquivo, console e artefato, inclusive modo `once`.
- O scheduler em shell executa cada `scheduler_update()` sob um subprocesso
  controlado pelo helper Python, que conserva a trava até o encerramento.
  Em caso de hold ativo, erro ou prova de lock indisponível, não executa
  a gravação do ciclo normal.

O observador `inspect_operation()` mantém exclusivamente os estados
`operation_in_flight`, `lock_free_process_identity_unverified` e
`unverified`, sempre com `live_no_drain_authorized=false`.
A cobertura é validada por **um único teste agrupado**, sem duplicar
suítes de PID, backup ou rollback.

**Risco identificado na PR #1120 (corrigido na etapa seguinte):**
nessa versão os lockfiles ficavam em
`dashboard/state/dsm928-worker-operations`, substituível junto com
`/opt/dsm`. A etapa de travas fixas abaixo elimina essa dependência,
mas o coordenador ainda precisará reter seus próprios locks e validar
todos os processos antes e depois de qualquer atualização.

Esta mudança comprova **atividade local observável**, não quiescência
operacional concluída. Ainda faltam: prova de processo vivo para cada
Worker, confirmação da ausência de subprocessos/jobs em andamento,
barreira de comandos no Controller, `Agent.run_forever()` e executores
privilegiados nos hosts, confirmação autenticada entre hosts, posse
transacional do hold, atualização/rollback integrado e aceite em clone
com serviços completos. `--no-drain` segue read-only/exit 2 e
`live_no_drain_authorized=false`. **Não criar hold manual em produção**.

## Travas fixas em `/run` fora do swap de `/opt/dsm` (21/11/2026)

O `maintenance_hold_gate.py` passa a usar exclusivamente
`/run/capivara-dsm/worker-operations/<worker>.lock` em operação normal,
independentemente de `DSM_ROOT`, caminho da release ou cwd. Os Workers
**não criam, truncam nem removem** seus arquivos de lock; na ausência de
provisionamento válido, os ciclos mutadores são bloqueados (fail-closed).
O parâmetro opcional `lock_dir` do módulo existe apenas para testes
isolados, não é configurável via variável de ambiente nem usado pelos
entrypoints instalados.

A unidade `dsm-dashboard-worker.service` executa, com privilégios root,
`prepare_maintenance_worker_locks.py --user {{DSM_USER}} --group {{DSM_GROUP}}`
**antes** do supervisor. O inicializador usa um pai `/run/capivara-dsm`
e uma pasta `worker-operations` **root-owned**, sem escrita por grupo ou
outros (0755). Pré-cria **nove arquivos regulares 0600** pertencentes ao
usuário/grupo do Worker. Assim o Worker pode adquirir `flock`, mas não
renomear nem excluir o inode, porque a pasta é de root. A inicialização é
idempotente: reiniciar a unidade **não troca os inodes existentes**.
Arquivo pré-existente com owner, grupo, modo, links ou tamanho incorreto,
ou symlink, é recusado e impede a inicialização; não se tenta reaproveitar
evidência insegura nem alterar seus dados.

`/run` é estado operacional do sistema, independente do diretório de
instalação e preservado durante o swap de uma release. **Não é persistente
entre reinicializações do sistema**: o sistema recria os nove arquivos
antes de iniciar o Worker após o boot; não existe confirmação automática
de quiescência como resultado desse provisionamento.

O teste agrupado existente prova ausência => bloqueio, criação segura,
identidade de inode estável em reaplicação, `flock` ocupado/livre,
hold ativo e recusa de symlink. A prova de processo vivo/versão correta,
jobs despachados, Agent remoto, Controller HTTP, executor privilegiado
e operação de update/rollback **continua pendente**. Ainda não existe
coordenador nem writer da marca root-owned de manutenção, e o lock livre
isoladamente continua `live_no_drain_authorized=false`.
`update.sh --no-drain` permanece diagnóstico, exit 2. Sem deploy
ou reinício de jogos cliente como parte desta implementação.

## Evidência de identidade local do supervisor e nove Workers (21/11/2026)

O comando de leitura
`python3 /opt/dsm/dashboard/workers/worker_identity_diagnostic.py --inspect`
consulta a unidade systemd `dsm-dashboard-worker.service` e os processos
Linux, sem criar marcador de manutenção, modificar serviços, instalar pacotes
nem tocar em instâncias. Ele cruza `MainPID`, `ActiveState`, `SubState`,
`User` e `ControlGroup` com o processo pai em `/proc` e os **nove
filhos diretos** de `/proc/<MainPID>/task/<MainPID>/children`.

Para cada processo são exigidos PPID, UID efetivo, cgroup, interpretador e
caminho de script esperados para os nove Workers. São comparados
`PID + starttime` (ticks imutáveis de inicialização do kernel)
em **duas leituras** e a identidade da unidade systemd antes/depois.
Filho faltante, extra ou duplicado, troca de PID, cgroup divergente,
zumbi, erro de leitura ou troca de starttime => `unverified`.
Alternância normal de estado S/R não é tratada como reinício.

A saída JSON é puramente diagnóstica:
`supervisor_verified`, `workers_verified`, `workers` com PID/start_ticks
e lock_status, `locks_free_candidate`, `errors` e
**`live_no_drain_authorized=false`**. O comando sempre retorna **exit 2**
mesmo quando todos os nove filhos são identificados: nenhum script pode
converter o resultado em permissão por sucesso de exit code. Para observar
também as travas 0600, execute com o usuário de serviço do Worker, que
possui os arquivos; root não é aceito como substituto de identidade do
processo em `maintenance_hold_gate.py`.

**Limites:** a confirmação de identidade local não comprova ausência
de jobs iniciados por subprocessos, materializadores externos ou
comandos remotos, nem bloqueia novas tarefas do Controller/Agent.
Também não estabelece um fence estável entre a leitura e o swap.
O próximo contrato precisa de **coordenador mantendo locks** e ACK
autenticado dos Agents/Controller, além do journal de transação/rollback.
`--no-drain` continua read-only/exit 2 e
`live_no_drain_authorized=false` até os gates operacionais restantes.

## Etapa 2 — barreira exclusiva LOCAL de nove Workers (21/11/2026)

A função `dashboard/workers/local_worker_fence.py:local_worker_fence()`
implementa a primeira operação de **fencing real**, porém limitada ao
host Controller e aos nove ciclos mutadores já instrumentados. Ela é uma
API de contexto, **não** um comando de atualização; não é chamada pelo
`update.sh` nem por cron/systemd.

O coordenador local:
1. Exige marcador **root-owned válido e ainda dentro do TTL**, lido pelo
   leitor existente de `game_uptime_maintenance_hold.py`. O leitor agora
   também retorna o `transaction_id`, `issued_at` e `expires_at`
   somente no caso da evidência validada. Ausência, expiração, corrupção,
   marcador não confiável ou troca de transação impedem o contexto.
2. Abre os **nove inodes estáveis**, pré-criados no diretório root-owned
   `/run/capivara-dsm/worker-operations`, em ordem alfabética fixa, e
   adquire todos com `flock(LOCK_EX|LOCK_NB)` **sem aguardar**. Se qualquer
   lock estiver ocupado/inseguro ou ausente, libera todos os anteriores
   imediatamente e falha fechado. Não modifica/limpa os arquivos.
3. Enquanto mantém os nove locks, relê o marcador e chama o diagnóstico
   de identidade de processos introduzido na PR #1123. Exige supervisor
   verificado, nove filhos exatos e identidade estável, e relê novamente
   o mesmo marcador/ID antes de fornecer a evidência ao chamador.
4. **Mantém os nove locks durante todo o bloco de contexto** e libera-os
   ao sair, inclusive por exceção. Um segundo coordenador concorrente é
   rejeitado. A evidência limita o escopo a
   `nine_local_worker_cycles_only`, registra os nove locks e o ID da
   transação, e sempre declara `remote_agents_acked=false`,
   `external_jobs_acked=false`, `controller_http_acked=false` e
   `live_no_drain_authorized=false`.

**Importante:** isto não instala/remover o marcador; o writer root-only
com journal durável ainda está pendente. Não o criar manualmente em
servidores com clientes ativos. Este guard não impede um comando já
despachado de continuar em subprocesso, no Agent remoto, em HTTP ou em
serviços de materialização. O próprio marcador root-owned pode mudar
após a última leitura; o mecanismo não é autorização para swap e
**não altera o bloqueio `update.sh --no-drain` (exit 2)**.

O teste agrupado em `update_game_uptime_agent_run_forever_test.py`
confirma lock real ocupado para os nove Workers, exclusividade de duas
barreiras, limpeza das travas após falha, ausência de hold, identidade
inválida, troca de `transaction_id` e operação ainda em voo. Não
acrescentar novos testes redundantes de PID/rollback já homologados.

**Restante da Etapa 2:** coordenador privilegiado que cria o marcador
com journal/fsync e preserva o fencing durante crash/recovery,
barreira de tarefas delegadas/Controller HTTP e ACK autenticado de
cada Agent remoto com geração de lease, fencing de threads/executores
privilegiados e checagem de versões compatíveis. Só após isso iniciar
a Etapa 3 de `update.sh` efetivamente transacional.

## Etapa 2 — recibo autenticado de evidência remota, sem ACK (21/11/2026)

O contrato **opt-in diagnóstico** dsm928-fence-evidence-readonly-v1
foi implementado no heartbeat Controller/Agent existente, respeitando
a autenticação já estabelecida por AgentPairingRepository:

- Somente com DSM928_REMOTE_FENCE_DIAGNOSTIC=1 e um marcador root-owned
  **válido e não expirado**, o Agent pode construir a mensagem
  CapivaraNoDrainFenceEvidence. Inclui agent_id, nonce aleatório de 128
  bits por mensagem, transaction_id, issued_at, expires_at, observed_at,
  schema/contrato exatos e todas as flags de quiescência negativas
  (agent_workers_fenced=false, external_jobs_verified=false,
  live_no_drain_authorized=false). O campo é opcional; Controllers
  antigos podem ignorá-lo sem quebrar o heartbeat.
- **Depois** de autenticar as credenciais, o Controller compara o ID da
  mensagem com o Agent autenticado, valida nonce, versão, emissão,
  expiração, TTL máximo de 900 s e observação com desvio até 30 s. Exige
  também seu **próprio marcador root-owned** com a mesma transação,
  emissão e expiração. Em sucesso retorna apenas
  status=authenticated_evidence_received_unfenced e
  remote_agent_quiescence_acked=false. Evidências inválidas são bloqueadas.
- O Agent só reconhece recibos vinculados ao nonce da solicitação atual,
  identidade do Agent, transação, geração, expiração, contrato exato e
  flags negativas. Uma resposta antiga, substituída ou tentando
  autorizar jogos/updater é rejeitada. wire_receipt_verified **não é ACK
  de quiescência**.

**Limitação operacional crucial:** quando o hold root-owned está ativo,
Agent.run_forever() suspende o heartbeat normal para impedir reconciliação
e despacho de comandos. Esta PR preserva essa guarda: o novo contrato
constitui um **ensaio autenticado de transporte/correlação**, ainda
**não um handshake operacional durante manutenção**. Nunca chamar
o heartbeat mutador para contornar a proteção. O próximo incremento
deve prover um canal dedicado estritamente somente leitura capaz de
responder durante o hold sem chamar record_agent_heartbeat() nem
enviar comandos.

Não existe journal durável de nonce: um pacote autenticado inteiro ainda
poderia ser repetido dentro da janela temporal. A checagem do nonce
impede aplicar um recibo de uma solicitação a **outra**, mas não demonstra
unicidade global. Antes de qualquer ACK positivo, são indispensáveis
lease/geração sob coordenador autenticado, replay cache persistente,
inventário de **todos** os Agents e conclusão real das threads, jobs
externos e executores privilegiados.

**Garantia atual:** #928 OPEN; update.sh --no-drain read-only/exit 2,
live_no_drain_authorized=false. Nenhum host ou jogo foi alterado.

## Etapa 2 — observação remota durante hold sem heartbeat mutador (21/11/2026)

A conexão opt-in do Agent ao Controller agora possui um endpoint **separado**:
POST /api/agent/no-drain/observe. A unidade de roteamento
dashboard/server_part11.py envia esse endereço exclusivamente para
dispatch_fence_observation(), em vez de dispatch_heartbeat().

- O Controller usa AgentPairingRepository.authenticate_readonly():
  valida credencial permanente, hash, fingerprint, estado da credencial
  e identidade do Agent com apenas SELECT, sem UPDATE last_used_at,
  registro de heartbeat, abertura de incidentes ou distribuição de jobs.
- O endpoint só aceita um objeto contendo no_drain_fence_evidence.
  Campo de comando, result_flush ou outros payloads são rejeitados
  com 400 antes de autenticar; credenciais inválidas retornam 401.
  Somente a função receipt_for_authenticated_agent(), já homologada
  na PR #1126, pode produzir o recibo negativo vinculado ao marcador
  root-owned do Controller.
- Com DSM928_REMOTE_FENCE_DIAGNOSTIC=1, o Agent já em execução
  **durante o hold** chama observe_remote_fence_readonly(config)
  no máximo uma vez por intervalo de heartbeat (mínimo 10 s).
  A função só constrói o envelope se o hold local for válido,
  usa _post() no endpoint dedicado e verifica o recibo. Não chama
  _inventory(), heartbeat(), _write_config(), reconcile_all(),
  processos de instalação, tratamento de comandos ou jogos.
  Erros geram apenas notificação de categoria em stderr, sem credenciais.
  O heartbeat e a reconciliação normais permanecem pausados.
- Quando o Agent arranca já com um marcador ativo, o guard anterior
  à carga de config/enroll permanece inalterado, sem executar sequer
  este diagnóstico. Isto é **fail closed** e deverá ser contemplado
  pelo coordenador/recovery antes de liberar no-drain.
- A autenticação do endpoint só lê o banco; não grava last_used_at.
  Os testes agrupados verificam rejeição de comandos, autenticação
  somente leitura, ausência de heartbeat mutador, credenciais erradas,
  identidade falsa, marcador ausente, nonce e lease verificados.

Esta capacidade permite **trocar recibos negativos durante o hold**
somente quando ambos os hosts já possuem marcadores root-owned da
mesma transação. Ainda não existe writer/coordenador que crie e recupere
marcadores, replay cache durável, fence real de threads/background
workers/executores privilegiados remotos, journal ou ACK positivo.
Receber o recibo NÃO é quiescência. #928 permanece OPEN,
live_no_drain_authorized=false, update.sh --no-drain continua
diagnóstico/exit 2, e o release permanece bloqueado.


## Etapa 2 — bloqueio dos três despachantes mutadores de Agent no Controller (21/11/2026)

`dashboard/agent_remote_http.py` agora verifica o hold local **antes da primeira
chamada ao repositório** nos despachantes `dispatch_enroll()`,
`dispatch_heartbeat()` e `dispatch_uninstall_result()`. Quando
`game_uptime_maintenance_hold.observe()` indica bloqueio ativo — inclusive
marcador expirado, inválido ou apenas journal pendente após reboot — ou a
leitura falha inesperadamente, os três retornam HTTP **423** com
`controller_maintenance_hold_active`, sem autenticar, registrar heartbeat,
despachar comandos, registrar instalação ou aceitar resultado de remoção.
Não inclui token, ID de cliente ou outros segredos na resposta.
Sem hold, o fluxo existente não muda.

O endpoint separado `POST /api/agent/no-drain/observe` **continua disponível**
por seu contrato autenticado `SELECT`-only de recibo negativo, sem comando ou
ACK positivo.

**Comprovação:** teste agrupado já existente em
`tests/update_game_uptime_sqlite_http_integration_test.py` usa listener HTTP
local + SQLite descartável para verificar bloqueio no heartbeat real, ausência
de alteração de `last_used_at` e quantidade de inventário, proibição de
enrollment/uninstall antes de autenticar e retomada do heartbeat sem hold.
Inclui evidências de hold válido, expirado, journal pendente e falha de leitura.

**Limite crítico:** a verificação é **admissão de nova requisição** e não
retém um lock durante toda a chamada. Requisição que entrou antes do marcador
pode continuar a executar; Console Push, outras rotas HTTP, jobs assíncronos,
materializers, threads internas e Agents remotos ainda exigem fencing próprio.
Ela não substitui a posse exclusiva de lease/journal coordenado com ACK
autenticado de todos os hosts e contagem de operações em voo. **Não é uma
barreira distribuída concluída.** Permanece `live_no_drain_authorized=false`,
`update.sh --no-drain` apenas diagnóstico/exit 2, issue #928 aberta e
release bloqueado. Nenhuma alteração em instalações ou jogos reais.


## Etapa 2 — inventário *in-flight* dos três despachantes HTTP do Controller (21/11/2026)

Complemento da barreira de ADMISSÃO introduzida na PR #1132.
`dashboard/game_uptime_controller_http_inflight.py` instrumenta os três
despachantes (`enroll`, `heartbeat`, `uninstall_result`) com contagem
sincronizada por processo. A entrada incrementa a contagem **antes** da
verificação de hold; a saída decrementa em `finally`, inclusive em erro ou
HTTP 423. `observe_controller_agent_inflight()` fornece PID, geração
monotônica e contagens por rota em uma só leitura sincronizada. Não registra
credenciais/payloads e não altera respostas, gravações ou filas normais.

O teste agrupado na suíte SQLite/HTTP existente simultaneamente mantém
as três funções em voo, verifica os três contadores, solta as chamadas,
confirma retorno a zero, incremento de geração, limpeza por exceção e
flags negativas. A suíte completa `update_game_uptime_*` continua no
mesmo gate; não há nova rodada de testes redundantes de PID ou rollback.

**Limitação decisiva:** é somente contagem **dentro de um único PID Python**.
Requisições de processos anteriores/outros, Console Push, endpoints
administrativos e do cliente, materializadores, subprocessos e tarefas
externas não são cobertos. A leitura em zero não é posse de lock e pode
mudar logo após a observação; o contador reinicia junto com o processo.
Portanto **nenhuma contagem, nem zero, concede ACK de Controller, quiescência
remota ou autorização `--no-drain`**. A próxima barreira deve usar locks
interprocessos estáveis provisionados por root, revalidar journal/lease sob
posse exclusiva e incluir os demais mutadores antes de integrar o updater.
Issue #928 permanece aberta, `live_no_drain_authorized=false`.


## Etapa 2 — fence interprocessos dos três Agent HTTP dispatchers (21/11/2026)

Complemento da #1133, **sem habilitação automática**. O arquivo
`dashboard/game_uptime_controller_agent_http_flock.py` implementa uma
barreira **interprocessos** com `flock` em um inode estável:
`/run/capivara-dsm/controller-agent-http.lock`. O arquivo fica fora de
`/opt/dsm`, em diretório root-owned, não gravável por usuários não-root.
Seu inode deve ser **provisionado pelo root** com proprietário usuário/grupo
de serviço do Dashboard, modo `0600`, conteúdo vazio, um único hardlink e
`O_NOFOLLOW`; a preparação idempotente rejeita permissões, proprietário,
symlink ou hardlink existentes inseguros, sem substituir nem reparar
automaticamente.

`dashboard/prepare_controller_agent_http_lock.py` oferece o preparador
privilegiado `--user/--group`. **Não está ligado a
`dsm-dashboard.service`, updater, bootstrap ou Agent:** sua instalação e
ativação ficam para uma futura homologação operacional isolada. Não executar
em hosts com jogos ativos nesta etapa.

Quando `DSM928_CONTROLLER_AGENT_HTTP_FLOCK=1` estiver configurado em um
**Controller descartável com o inode validamente provisionado**, os três
despachantes `enroll`, `heartbeat`, `uninstall_result` seguram
`LOCK_SH|LOCK_NB` durante sua execução completa, desde antes da checagem do
hold root-owned, liberando em `finally` mesmo sob erro. Arquivo
ausente/alterado/inseguro ou lock exclusivo ocupado gera HTTP `423`
`controller_http_interprocess_fence_unavailable` sem atingir o código de
autenticação mutadora. Sem opt-in, o contrato anterior permanece inalterado
para não introduzir regressão nos Controllers existentes.

Um futuro coordenador privilegiado pode tomar o **mesmo** inode com
`LOCK_EX|LOCK_NB`, permanecendo exclusivamente dono do lock durante todo
o bloco de contexto; uma chamada que já detenha lock compartilhado faz a
tentativa falhar imediatamente, e uma nova chamada opt-in falha com 423
enquanto o lock exclusivo estiver ocupado. A API de exclusividade fornece
**somente evidência local negativa** (`controller_http_acked=false`,
`remote_agents_acked=false`, `external_jobs_acked=false`,
`live_no_drain_authorized=false`), sem instalar hold, limpar journal
ou invocar updater. **Não é permissão para update.**

O teste agrupado na suíte HTTP/SQLite já existente exercita provisionamento
idempotente em diretório temporário, exclusão real entre **dois processos
Python**, um heartbeat ainda em voo, recusa de nova requisição sob lock
exclusivo e recusa de inode inseguro. O CI usa o gate completo de #928, sem
repetir a bateria de PIDs/rollback.

**O que ainda falta na Etapa 2:** habilitação/provisionamento somente após
verificar que **todos** os processos Controller receberam a instrumentação;
abranger demais rotas HTTP, Console Push e operações assíncronas, jobs
externos e materializers; integrar posse de locks com hold/journal durável,
reconciliação e ACK operacional autenticado de **cada Agent remoto**. Lock
local livre ou exclusivo dos três handlers **jamais** prova quiescência
distribuída. Issue #928 segue OPEN; `update.sh --no-drain` segue
somente diagnóstico/exit 2, e release continua bloqueado.


## Etapa 2 — Console Push sob a mesma barreira de Agent HTTP (21/11/2026)

`dashboard/agent_console_push.py` agora aplica o mesmo
`shared_controller_agent_http_lock()` opt-in introduzido na PR #1134 durante
**toda** a requisição HTTP chunked de Console Push
(`/api/agent/console/stream`). O stream é de longa duração; portanto, se uma
sessão já está aberta, o futuro coordenador **não** consegue tomar
`LOCK_EX|LOCK_NB` até ela encerrar. Com lock exclusivo em posse do
coordenador, uma nova conexão é recusada com **HTTP 423 antes da
autenticação** ou de qualquer atualização do buffer em memória. Sem
`DSM928_CONTROLLER_AGENT_HTTP_FLOCK=1`, a aquisição do inode continua
desativada por padrão.

A verificação read-only de hold root-owned é aplicada **mesmo sem opt-in**,
antes da autenticação, e novamente **após ler cada chunk e antes de aceitar
keepalive, tocar a presença ou ingerir eventos**. Assim, uma conexão já
aberta que receba um novo frame durante a manutenção deixa de publicar
console lines: devolve HTTP 423. Se a evidência for inválida, expirou,
não for legível ou houver journal pendente, falha fechado sem limpar ou
substituir os dados. O loop existente mantém o timeout de socket de 15s;
nenhuma thread nova, restart, comando de game ou integração com o updater.

O teste agrupado na suíte `update_game_uptime_sqlite_http_integration_test`
verifica (i) hold bloqueando antes de autenticação, (ii) lock EX rejeitando
uma conexão nova, (iii) um stream já admitido segurando SH enquanto o
coordenador tenta EX, (iv) stop de ingestão após o primeiro chunk quando
um hold aparece antes do segundo. Os testes anteriores de cursor, chunk
NDJSON e propriedade da instância continuam no seu módulo legado.

**Limites:** a barreira é opcional e não cobre ainda outras APIs HTTP,
clientes administrativos, todos os subprocessos/threads/jobs nem Agents
remotos. As linhas já aceitas antes do hold são preservadas; a conexão
pode continuar viva até o próximo chunk/timeout, mantendo SH nesse
intervalo. Nenhuma evidência nesse fluxo é ACK positivo ou autorização de
`update.sh --no-drain`. #928 segue aberta / Etapa 2 parcial.


## Etapa 2 — admissão de instalação e teste de conexão de Agent (21/11/2026)

Os dois POSTs do Controller `/api/agents/installations` e
`/api/agents/installations/test-connection` agora obedecem ao mesmo leitor
`game_uptime_maintenance_hold.observe()` já utilizado no fluxo Agent:
hold ativo, inválido, ilegível ou journal pendente bloqueia com HTTP 423,
**antes** de iniciar instalação remota ou prova de conexão. A ausência
comprovada de hold preserva o comportamento existente.

Quando `DSM928_CONTROLLER_AGENT_HTTP_FLOCK=1` estiver explicitamente
habilitado em homologação isolada, cada operação mantém o **mesmo**
`shared_controller_agent_http_lock()` da #1134 durante toda a chamada;
um `LOCK_EX` concorrente impede nova entrada e uma instalação já em voo
impede a posse exclusiva até terminar. Nenhum novo lockfile, flag, writer ou
protocolo foi criado. Falhas de aquisição são fail-closed; retornos continuam
sempre com `live_no_drain_authorized=false` e ACKs negativos.

A prova agrupada adicionada à suíte SQLite/HTTP #928 cobre ambas as rotas,
hold ativo/inválido/ilegível, exclusividade, conservação dos caminhos
originais na ausência de hold e chamada de instalação em voo. Nenhuma
instalação remota real é iniciada pelo teste (funções de conexão/instalação
são mocks). O novo módulo é incluído no filtro de CI de runtime.

**Escopo limitado:** isso cobre somente esses dois POSTs; outras rotas
administrativas, jobs, subprocessos já delegados, Agents remotos e
instalações iniciadas por outros canais continuam fora da barreira. A flag
interprocessos permanece **desabilitada por padrão**. Sem prova
distribuída de quiescência, `update.sh --no-drain` continua exit 2,
`live_no_drain_authorized=false`, issue #928 aberta e release bloqueado.


## Etapa 2 — barreira final de admissão HTTP do Controller (21/11/2026)

O entrypoint executado pelo systemd, `dashboard/server_part22.py`, instala
`install_controller_mutation_gate(legacy)` **por último**, depois de todos
os hooks Controller/Customer. O wrapper cobre todas as rotas atendidas por
`do_POST`, `do_PUT`, `do_PATCH` e `do_DELETE` existentes no
`DashboardHandler`, sem adicionar métodos HTTP antes inexistentes.

Cada chamada mutadora consulta o hold root-owned. Hold ativo/inválido/ilegível,
ou journal pendente com marcador ausente, retorna **HTTP 423** antes de chamar
o roteador original. Quando o flock de homologação
`DSM928_CONTROLLER_AGENT_HTTP_FLOCK=1` está explicitamente habilitado,
a chamada mantém a **mesma** trava compartilhada da #1134 enquanto roda;
`LOCK_EX` impede novas admissões e falha fechado quando uma requisição
já está em voo. A flag permanece desligada por padrão. Operações sem hold
mantêm o comportamento anterior.

A rota única `POST /api/agent/no-drain/observe` é exceção deliberada:
trata-se do transporte autenticado **somente leitura** das PRs #1126/#1127,
necessário sob hold e não pode emitir ACK positivo. A exceção é por caminho
exato (query string ignorada), nunca por prefixo. Rotas GET continuam
inalteradas e não são prova de imutabilidade universal.

Um único teste agrupado exercita quatro verbos, hold malformado/ilegível,
HTTP 423, exceção read-only, caminho normal, lock EX em disputa e operação
em andamento com lock SH real em temporário descartável. Teste verifica
também a ordem do hook final. Sem games, hosts, SSH, banco ou updater reais.

**Limites restantes:** esta prova não demonstra quiescência de GETs com
efeitos colaterais, jobs/threads/materializers já delegados, processos que
não entram pelo handler, nem Agents remotos. O wrapper também não garante
que instâncias Controller em hosts diferentes receberam o mesmo hold.
Sem proteção distribuída/ACK autenticado e coordinator journal/lease
operacional, #928 permanece aberta, `update.sh --no-drain` exit 2,
`live_no_drain_authorized=false` e release não autorizado.


## Etapa 2 — admissão dos dois auxiliares privilegiados do Agent (21/11/2026)

O materializador root `agents/linux/privileged/materialize_instance.py` e o
executor de comandos nativos `agents/linux/privileged/native_command.py`
agora chamam `require_privileged_mutation_admission()` **imediatamente
após a verificação de root e antes de ler um pedido**, consultar arquivos
de jogo, despachar comando, aplicar ou remover runtime. O leitor compartilhado
`game_uptime_maintenance_hold.observe()` só admite a execução se retornar
exatamente `{"active": false}`. Hold ativo/inválido, journal persistente
pendente ou erro de leitura recusam a operação, sem criar ou remover marcador.

No fluxo de erro legado do materializador, a concessão de leitura do cliente
para `apply` também é omitida se o hold estiver ativo, mantendo apenas o
resultado `status=failed` necessário ao diagnóstico. Ausência comprovada
de hold mantém a rotina anterior. O código não altera serviços systemd,
permissões em produção, world saves nem comandos de jogos.

**Única prova agrupada**: carrega os dois helpers reais em Python isolado,
impede qualquer acesso ao request usando mock, testa hold/journal/erro,
evidência ausente, comportamento sem hold e ausência de ACL de recuperação
quando o materializador é recusado. Não duplica ensaios PID/rollback.

**Limite decisivo:** é apenas uma barreira de *novas admissões* nos dois
entrypoints root, sem lock estável de processo em voo e sem coordenação de
outros helpers, jobs/threads já iniciados ou Agents externos. Uma operação
admitida antes de surgir o hold pode continuar. Não considerar quiescência
ou autorização de atualização sem drenagem; #928 OPEN,
`live_no_drain_authorized=false`, `update.sh --no-drain` exit 2,
release #1096 Draft.


## Etapa 2 — rastreio de operações em voo dos dois helpers privilegiados (21/11/2026)

Depois da PR #1139, `materialize_instance.py` e `native_command.py`
já recusavam **novas admissões** sob hold/journal. Esta alteração acrescenta
um mecanismo separado de **trava interprocessos**, ainda opt-in, cobrindo a
duração completa da função `run()` de ambos os helpers, e não apenas a
verificação inicial.

`agents/linux/runtime/game_uptime_privileged_flock.py` usa um inode fixo
`/run/capivara-dsm/agent-privileged-operations.lock` fora da árvore
substituída do Agent. O contexto `shared_privileged_helper_lock()` mantém
`flock(LOCK_SH|LOCK_NB)` até o fim da operação ou exceção. O futuro
coordenador root pode exigir `LOCK_EX|LOCK_NB` para comprovar que **os dois
tipos de helpers instrumentados** não estão em execução no host e bloquear
novas chamadas opt-in durante a posse exclusiva. A identidade do inode é
verificada com `O_NOFOLLOW`, proprietário, grupo, modo `0600`,
`nlink=1`, tamanho zero, inode/dispositivo estáveis e pais root-owned sem
escrita por terceiros. A função de preparação idempotente cria somente inode
ausente e **não substitui, limpa ou repara** artefatos existentes inseguros.

O recurso depende **explicitamente** de
`DSM928_AGENT_PRIVILEGED_FLOCK=1`. Ele permanece **desativado por padrão**
e o provisionador **não é chamado por installer, updater ou systemd**.
Sob opt-in, arquivo ausente, inseguro ou ocupado falha fechado antes de
ler requisição/configuração ou executar ações de jogo. O main de erro do
materializador também exige uma trava SH durante a possível correção de
ACL, além do leitor de hold; um EX ocupado impede essa mutação de recuperação.
A emissão de um resultado diagnóstico de falha permanece permitida.

A prova agrupada da suíte
`tests/update_game_uptime_privileged_helpers_test.py` carrega as **duas
funções `run()` reais**, sem executar ações externas; cada uma é
suspensa antes de ler o request, enquanto um **segundo PID Python** tenta
adquirir EX e é recusado. Após terminar cada operação, o EX passa.
Um EX mantido pelo teste rejeita novas invocações dos dois helpers e impede
a recuperação de ACL; inode adulterado é recusado. Todos os arquivos e
processos são temporários. Os testes de permissões, PIDs e rollback já
existentes não foram duplicados.

**Limitações decisivas:** a posse EX cobre somente esses dois pontos de
entrada **e apenas se todos os processos instrumentados tiverem o opt-in
habilitado previamente**. Subprocessos que continuem após a saída da
função pai, jobs disparados por outros caminhos, serviços privilegiados
adicionais, threads do Agent, Controller/Worker e outros hosts seguem fora
da barreira. O lock usa `O_CLOEXEC` e não pretende representar a duração
de processos filhos destacados. O exclusivo retorna obrigatoriamente
`privileged_helper_acked=false`, `external_jobs_acked=false`,
`remote_agents_acked=false` e `live_no_drain_authorized=false`.
Não é um lease distribuído, não cria/renova/recupera journal e não
habilita `update.sh --no-drain`. A issue #928 segue aberta, Etapa 2
parcial e release bloqueado. Nenhum host em produção foi modificado.


## Etapa 2 — observação local conjunta do journal e trava dos helpers root (21/11/2026)

Depois da PR #1140, `game_uptime_privileged_journal_witness.py`
acrescenta um **leitor somente diagnóstico** que mantém a posse exclusiva
`LOCK_EX|LOCK_NB` do inode de helpers
`/run/capivara-dsm/agent-privileged-operations.lock`, enquanto verifica
o hold root-owned e o **journal persistente da mesma transação**.

O leitor exige transaction_id hexadecimal esperado, UID root nos caminhos
instalados, `O_NOFOLLOW`, arquivo de journal regular com inode estável,
`0600`, `nlink=1`, conteúdo bounded, pais seguros, contrato exato
`CapivaraDSMNoDrainPendingJournal` e `state=prepared_requires_distributed_fence`.
As identidades da transação (`transaction_id`, `issued_at`,
`expires_at`) devem corresponder exatamente ao marcador de hold e a
janela de lease não pode estar expirada. Faz uma **segunda verificação antes
de soltar EX**. Qualquer ausência, adulteração, troca de inode, erro de
leitura, SH ocupado ou transação cruzada falha fechado. Não escreve,
renova ou apaga journal/hold; caminhos temporários/UID injetáveis são
somente para testes descartáveis.

A evidência exposta tem escopo explícito **dois helpers root parent
opt-in neste host**. Mesmo com journal local consistente e trava EX em
posse, o retorno mantém `privileged_helper_acked=false`,
`controller_http_acked=false`, `external_jobs_acked=false`,
`remote_agents_acked=false`, `live_no_drain_authorized=false` e
`all_helper_processes_opted_in_verified=false`. O coordenador de
manutenção distribuído **não** chama esse leitor automaticamente. Não
incorpora autorização de update ou rollback e não afirma que os outros
processos usam o lock.

**Teste agrupado** na suíte persistente #928: prepara journal e hold em
arquivos temporários; exige EX; mantém SH de helper em voo e comprova
negação, expiração de lease, ID divergente, journal alterado, alteração
durante a posse de EX, symlink e integridade de arquivos sem escrita pelo
leitor. Não cria outra bateria de PID ou systemd.

Permanecem pendentes na Etapa 2: comprovar instrumentação e posse de lock
de **todos** os processos de cada host, incluir Controller/Workers,
subprocessos destacados e demais jobs, materializar barreira distribuída
com ACK autenticado/anti-replay por Agent e coordenar renovação/recovery
do lease. `DSM928_AGENT_PRIVILEGED_FLOCK` permanece **off** por padrão;
não ligar em Horizon/VPS antes da homologação operacional. `update.sh
--no-drain` continua somente diagnóstico/exit 2, issue #928 aberta e
release bloqueado.


## Etapa 2 — operações root de backup e firewall no mesmo fence em voo (21/11/2026)

Foram adicionados **três entrypoints privilegiados** ao mecanismo opt-in já
adotado por `materialize_instance.py` e `native_command.py`:
`create_instance_backup.py`, `restore_instance_backup.py` e
`reconcile_firewall.py`. Os cinco processos root compartilham **um único
inode**, `/run/capivara-dsm/agent-privileged-operations.lock`,
protegido por `flock(LOCK_SH|LOCK_NB)` durante toda a função `run()`.
O coordenador só consegue adquirir `LOCK_EX|LOCK_NB` quando nenhum dos
cinco *pais de helpers instrumentados e com opt-in ativo* está executando.
O diagnóstico de posse EX passou a nomear cinco funções, mantendo todos
os flags de ACK e autorização em **false**.

O leitor root-owned de hold/journal pendente é consultado **antes** de ler
o request ou iniciar `backup_client`, restauração de world/save ou
`reconcile_ufw`. Sob hold ativo/inválido/ilegível/journal pendente, novas
operações de backup e firewall são recusadas. No reconciliador firewall,
o comportamento anterior de produzir resultado de falha é preservado;
um lock EX já ocupado impede a execução antes da criação de side effects.
A ausência comprovada de hold, com
`DSM928_AGENT_PRIVILEGED_FLOCK` desligada (padrão), conserva o fluxo
existente. Não foram alterados serviços systemd, portas, ACLs ou
arquivos de jogo.

A prova **agrupada** em
`tests/update_game_uptime_privileged_helpers_test.py` carrega as três
funções reais com mocks de leitura/resultado, confirma bloqueio antes
do request, mantém cada helper em voo e usa um **segundo PID Python**
para provar que a posse exclusiva é recusada. Quando EX já está em
posse, todos os três são negados antes de I/O; inode adulterado é
recusado. Os testes de backup, firewall, runtime e rollback existentes
continuam aplicáveis, sem criar cópias da bateria de PIDs.

**Limite essencial:** o lock não atesta jobs não instrumentados,
filhos destacados, estados do Supervisor, backup em threads do Agent
ou Agents remotos; nem prova que todos os processos foram atualizados
e receberam a flag opt-in. `game_uptime_privileged_journal_witness`
continua somente diagnóstico local e
`all_helper_processes_opted_in_verified=false`. A flag permanece
desativada por padrão e não foi ligada a installer/updater/serviços;
`update.sh --no-drain` segue bloqueado (exit 2), a issue #928 aberta,
release #1096 Draft. Não houve deploy/restart de produção.
