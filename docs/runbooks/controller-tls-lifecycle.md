# Ciclo de vida TLS do Controller

O Controller carrega cada par de uma geração imutável em
`/etc/capivara/tls/versions`. A rotação troca um único link, exige HTTPS
verificado com o leaf esperado e HTTP 200 em `/health` com estado `healthy`.
Uma falha restaura o link anterior e verifica o HTTPS novamente. Conexões
abertas mantêm seu contexto TLS. A rotação não usa restart nem opera sobre
unidades de jogo.

## Procedimento único de homologação Horizon + VPS

Use a topologia Horizon + VPS aprovada para ensaio, com CA confiável nos dois
hosts e um Agent ativo no VPS. Qualquer intervenção em hosts reais precisa de
autorização operacional própria. Registre versão, SHA, horários UTC e resultados
no mesmo registro. Use a suíte **Controller TLS Transport** do HEAD aprovado
para a prova isolada de falhas, rollback e permissões. A etapa integrada usa
somente renovação normal e observação. Mantenha a #1161 aberta até anexar as
evidências e mantenha a release #1096 em HOLD.

### 1. Instalar o componente em janela autorizada

No Horizon, use o pacote já assinado para o commit aprovado, com os sidecars
do mesmo artefato, em diretório root-only. Substitua as variáveis abaixo pelos
caminhos absolutos e pelo SHA registrado na revisão. Use o verificador e a
âncora de confiança da instalação #928 existente, fora do pacote candidato.

```bash
export REVIEWED_SHA='<SHA de 40 caracteres>'
export ARCHIVE='/root/dsm-tls/capivara-dsm-<versão>.tar.gz'
export MANIFEST='/root/dsm-tls/release-manifest.json'
export STATEMENT='/root/dsm-tls/<prova assinada>.json'
export SIGNATURE='/root/dsm-tls/<assinatura>.sig'
sudo --preserve-env=REVIEWED_SHA,ARCHIVE,MANIFEST,STATEMENT,SIGNATURE bash -eu <<'BASH'
owner=/usr/local/libexec/capivara-dsm-928-updater/update-manager
/usr/bin/python3 -I -S -B - "$owner" "$ARCHIVE" "$MANIFEST" "$STATEMENT" "$SIGNATURE" "$REVIEWED_SHA" <<'PY'
import importlib.util
from pathlib import Path
import sys
owner, archive, manifest, statement, signature, sha = sys.argv[1:]
spec = importlib.util.spec_from_file_location("provenance", Path(owner) / "game-uptime-release-provenance.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.verify_signed_release(
    Path(archive), Path(manifest), Path(statement), Path(signature), expected_commit=sha
)
assert result["artifact_signature_verified"]
print("artifact_signature_verified", result["git_commit"])
PY
export DSM_ROOT=/opt/dsm
log_error() { printf '%s\n' "$*" >&2; }
source /opt/dsm/update-manager/verify-release.sh
verify_release "$ARCHIVE" "$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
install -d -m 0700 /root/dsm-tls/staging
stage=$(mktemp -d /root/dsm-tls/staging/candidate.XXXXXX)
tar --no-same-owner -xzf "$ARCHIVE" -C "$stage"
find "$stage" -mindepth 2 -maxdepth 2 -type f -name version -printf '%h\n'
BASH
```

Defina `PKG_ROOT` com o caminho impresso. Esta instalação inicial altera
installer, systemd e updater e requer a janela de manutenção convencional.
O classificador restrito da #928 não autoriza `--no-drain-execute` para este
pacote. O atualizador convencional pode drenar jogos durante **essa janela**.
O Controller pode reiniciar na instalação inicial. A prova de PIDs da rotação
começa depois da estabilização, com os jogos esperados novamente ativos.

```bash
PKG_ROOT='/root/dsm-tls/staging/candidate.<id>/capivara-dsm-<versão>'
sudo "$PKG_ROOT/update.sh" "$PKG_ROOT"
sudo bash -eu -c 'source "$1/installer/web_transport.sh"; install_controller_tls_lifecycle' _ "$PKG_ROOT"
sudo stat -c '%u:%g %a %h %s %F' /var/lib/capivara-dsm-928/updater-admission.lock
```

O inode existente deve ser arquivo regular root:root, modo 600, link count 1
e tamanho zero. Ausência ou identidade inesperada em host com o estado ou o
owner da #928 bloqueia o enrollment e as rotações. Use o procedimento de
recuperação da #928 para corrigir isso. O componente TLS nunca cria ou substitui
esse inode. Em instalação genuinamente legada, sem
`/var/lib/capivara-dsm-928` e sem
`/usr/local/libexec/capivara-dsm-928-updater`, um administrador pode registrar
`"legacy_without_dsm928": true` e excluir concorrência com manutenção por
procedimento operacional. Remova essa opção ao migrar para #928.

Se a implantação usa caminhos personalizados, migre para o par nativo
`/etc/capivara/tls/server.crt` e `server.key` na janela inicial. Mantenha uma
cópia root-only do par e da configuração anteriores, verifique o acesso à chave
como conta de serviço e verifique HTTPS antes do enrollment. Para instalações
com caminho legado, o loader novo detecta `active` automaticamente. Ao
persistir caminhos em uma alteração autorizada posterior, use
`/etc/capivara/tls/active/server.crt` e `server.key` para que código de uma
versão anterior também possa abrir o par ativo.

### 2. Migrar DNS-01 manual e confirmar o destinatário

Registre a lineage existente com `sudo certbot certificates`, o fingerprint
servido e a validade. Preserve a lineage e o par DSM válido durante a migração.
Inspecione a configuração protegida de renovação para hooks antigos de
pre/post/deploy que escrevam no DSM ou reiniciem serviços. A lineage nova deve
usar apenas os hooks de desafio necessários. Coordene a janela para que
nenhuma execução do Certbot legado esteja em curso ou possa iniciar até o
enrollment aposentar o hook global DSM. Preserve o agendamento das outras
lineages. Antes do enrollment, guarde uma cópia do hook legado em storage
root-only quando ele existir.

DNS-01 manual serve apenas para emissão interativa e fica sem timer. Para
migrar, emita sob **outro nome de lineage**, mantendo o hostname e a CA
aprovados. Os dois scripts devem ser executáveis e root-owned, sem permissões
de escrita por outros usuários em seu caminho. Guarde credenciais do DNS fora
dos argumentos, em arquivo root-only modo 0600. Os scripts devem restringir a
permissão aos TXT de desafio e evitar saída com segredos.

```bash
TLS_HOST='controller.example.com'
LINEAGE="${TLS_HOST}-dsm-unattended"
ACME_EMAIL='acme-admin@example.com'
TLSCTL=(sudo /usr/bin/python3 -I -S -B /etc/capivara/controller-tls-lifecycle.py)
"${TLSCTL[@]}" --verify-hook /etc/capivara/acme/auth
"${TLSCTL[@]}" --verify-hook /etc/capivara/acme/cleanup
sudo certbot certonly --non-interactive --agree-tos --no-directory-hooks \
  --cert-name "$LINEAGE" --email "$ACME_EMAIL" -d "$TLS_HOST" \
  --manual --preferred-challenges dns \
  --manual-auth-hook /etc/capivara/acme/auth \
  --manual-cleanup-hook /etc/capivara/acme/cleanup
```

Um plugin DNS instalado pode substituir as opções `--manual` e dos hooks pelas
opções e pelo arquivo de credenciais da sua documentação. Para HTTP-01 use
`--standalone --preferred-challenges http` e TCP/80 público disponível. Se
necessário adicione `--server "$ACME_DIRECTORY"` com o endpoint HTTPS aprovado.
Use a opção externa se a CA não fornecer staging compatível com o dry-run do
Certbot ou se outro sistema já fizer a emissão.

Obtenha a conta com
`systemctl show dsm-dashboard.service -p User -p Group`. Edite
`/etc/capivara/controller-tls.json` com `sudoedit` e aplique owner root:root e
modo 0600 antes de executar o helper. Exemplo para a lineage criada acima:

```json
{
  "hostname": "controller.example.com",
  "address": "127.0.0.1",
  "port": 8443,
  "service_user": "dsm",
  "service_group": "dsm",
  "certbot_lineage": "controller.example.com-dsm-unattended",
  "alert_to": "dsm-admin@example.com"
}
```

Use a porta HTTPS interna e o endereço local numérico alcançável. Para CA
privada, defina `ca_file` com o caminho raiz-controlado da CA e configure a
mesma confiança no VPS e nos Agents. Para fonte externa substitua
`certbot_lineage` por `source_cert` e `source_key` com os caminhos absolutos de
`fullchain.pem` e da chave PEM sem senha. O publisher automático deve trocar
uma geração de origem por link atômico, com chave root-only modo 0600. Registre
a execução bem-sucedida desse publisher, pois o helper testa o par publicado e
a prontidão, enquanto a política de emissão fica no sistema externo.

Configure um MTA local com interface `/usr/sbin/sendmail` e rota para a caixa
monitorada `alert_to`. Confirme a chegada da mensagem **delivery_test** na
caixa do administrador antes de executar o enrollment. Registre assunto e
horário de recebimento, sem expor endereço privado ou conteúdo de logs.

```bash
sudo chown root:root /etc/capivara/controller-tls.json
sudo chmod 0600 /etc/capivara/controller-tls.json
"${TLSCTL[@]}" --verify-active
"${TLSCTL[@]}" --test-alert
# Prossiga após confirmar o recebimento de delivery_test.
"${TLSCTL[@]}" --enroll
```

O enrollment toma a admissão e faz `certbot renew --non-interactive --dry-run`
somente para a lineage configurada. Exige HTTPS atual válido, valida cadeia,
hostname, vigência, chave e leitura pela conta de serviço na fonte e testa o
MTA. Só então retira o hook global legado, caso exista, e autoriza a
configuração. O par servido permanece intacto. Confirme
`enrollment_preflight_passed` e o recebimento de **enrollment_test**.
Persistir outra configuração exige repetir o enrollment antes de voltar a
rodar o timer.

### 3. Provar rotação e continuidade nos dois hosts

No Horizon e no VPS, use um diretório de evidências privado e capture o mesmo
conjunto de jogos observados. Falhe se estiver vazio ou faltar um jogo
esperado. Use a mesma função antes e depois da rotação.

```bash
set -o pipefail
umask 077
EVIDENCE=$(mktemp -d /tmp/dsm-tls-evidence.XXXXXX)
snapshot_games() {
  local unit pid ticks
  while read -r unit; do
    pid=$(systemctl show "$unit" -p MainPID --value) || return
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    ticks=$(sudo awk '{sub(/^.*\) /,""); print $20}' "/proc/$pid/stat") || return
    [[ "$ticks" =~ ^[0-9]+$ ]] || return 1
    printf '%s %s %s\n' "$unit" "$pid" "$ticks"
  done < <(systemctl list-units 'capivara-instance-*.service' --state=running \
    --no-legend --plain | awk '{print $1}' | sort)
}
snapshot_games >"$EVIDENCE/games.before"
test -s "$EVIDENCE/games.before"
date -u +%FT%TZ >"$EVIDENCE/start"
# Somente no Horizon:
systemctl show dsm-dashboard.service -p MainPID -p NRestarts \
  -p ExecMainStartTimestampMonotonic >"$EVIDENCE/controller.before"
```

No VPS, defina o hostname e a porta públicos, o ID/instância observados e o
caminho de um cookie jar Netscape modo 0600 de sessão Controller autorizada
com `console.read`. Use a confiança normal do sistema. Em ambiente de CA
privada, a CA deve estar instalada também no trust store normal do Agent.
Não use opções que desabilitem validação TLS.

```bash
TLS_HOST='controller.example.com'
TLS_PORT=443
AGENT_ID='<ID do Agent no VPS>'
INSTANCE_ID='<ID da instância observada>'
COOKIE_JAR='/caminho/privado/controller.cookies'
URL="https://$TLS_HOST:$TLS_PORT"
public_tls() {
  openssl s_client -connect "$TLS_HOST:$TLS_PORT" -servername "$TLS_HOST" \
    -verify_hostname "$TLS_HOST" -verify_return_error -showcerts </dev/null >"$1.handshake" \
    && grep -F 'Verify return code: 0 (ok)' "$1.handshake" \
    && openssl x509 -in "$1.handshake" -noout -fingerprint -sha256 -enddate \
    && curl -qfsS --max-time 10 "$URL/health" | jq -e '.status == "healthy"'
}
console_events() {
  curl -qfsSN --max-time 30 --cookie "$COOKIE_JAR" --get \
    --data-urlencode "instance_id=$INSTANCE_ID" --data-urlencode 'auth_area=controller' \
    --data-urlencode 'limit=10' --data-urlencode 'timeout=25' \
    "$URL/api/customer/instance/workspace/console/stream" |
    awk '/^id: |^event: / {print; fflush()}'
  local statuses=("${PIPESTATUS[@]}")
  [[ "${statuses[1]}" == 0 && ( "${statuses[0]}" == 0 || "${statuses[0]}" == 28 ) ]]
}
public_tls "$EVIDENCE/before" | tee "$EVIDENCE/tls.before"
console_events >"$EVIDENCE/console.before"
grep -Fx 'event: console-snapshot' "$EVIDENCE/console.before"
```

No Horizon, habilite o timer e espere a ativação normal da nova lineage ou do
novo par externo. Se a primeira janela do timer já passou, aguarde até
`systemctl list-timers` indicar o disparo ou use o start abaixo para executar
a mesma unidade usada pelo timer. Não force reemissão nem reinicie serviços.

```bash
sudo systemctl enable --now dsm-controller-tls.timer
systemctl list-timers dsm-controller-tls.timer --no-pager
sudo systemctl start dsm-controller-tls.service
sudo journalctl -u dsm-controller-tls.service --since "$(cat "$EVIDENCE/start")" --no-pager |
  tee "$EVIDENCE/tls-journal"
grep -F 'activation_verified' "$EVIDENCE/tls-journal"
ROTATION_UTC='<timestamp UTC da linha activation_verified>'
```

No VPS, repita a verificação pública e observe atividade normal de console.
Use o horário de ativação obtido no Horizon.

```bash
ROTATION_UTC='<timestamp UTC da linha activation_verified>'
public_tls "$EVIDENCE/after" | tee "$EVIDENCE/tls.after"
sudo journalctl -u capivara-agent.service --since "$ROTATION_UTC" --no-pager |
  grep -F "heartbeat ok agent=$AGENT_ID health=online status=active" |
  tail -n 1 | tee "$EVIDENCE/heartbeat.after"
test -s "$EVIDENCE/heartbeat.after"
console_events >"$EVIDENCE/console.after"
grep -Fx 'event: console-snapshot' "$EVIDENCE/console.after"
grep -Fx 'event: console-line' "$EVIDENCE/console.after"
```

Nos dois hosts, compare os jogos. No Horizon compare também o Controller.

```bash
snapshot_games >"$EVIDENCE/games.after"
diff -u "$EVIDENCE/games.before" "$EVIDENCE/games.after"
# Somente no Horizon:
systemctl show dsm-dashboard.service -p MainPID -p NRestarts \
  -p ExecMainStartTimestampMonotonic >"$EVIDENCE/controller.after"
diff -u "$EVIDENCE/controller.before" "$EVIDENCE/controller.after"
"${TLSCTL[@]}" --verify-active
```

Aprove quando o pacote e o HEAD coincidirem, a suíte isolada estiver verde,
o administrador tiver confirmado recebimento, o timer estiver habilitado, o
VPS apresentar cadeia confiável e leaf novo igual ao fingerprint do
`activation_verified`, e o heartbeat autenticado for posterior à rotação.
O SSE deve ter snapshot antes e depois e pelo menos uma linha nova observada
depois. Registre o ID do evento quando disponível e o avanço da fonte de
console no horário UTC da captura para streams de journal sem ID por linha.
As identidades de processos de todos os jogos e o PID, início e contador de
restart do Controller devem ser idênticos. Anexe evidências redigidas à #1161.
Provas de falha ficam na CI e em fixtures descartáveis, sem injeção no
Horizon ou VPS reais.

## Alertas e recuperação

O timer roda após o boot e depois aproximadamente a cada seis horas. A
implementação envia alertas de 30, 15, 7, 1 dias e de expirado, além de
falhas acionáveis de renovação, ativação e recuperação. Se o host perder
várias janelas, a próxima execução reporta o limiar atual. O estado de
deduplicação só avança quando o MTA aceita o aviso. A aceitação na fila é
registrada como `administrator_alert_accepted_by_mta`; recepção na caixa é a
evidência operacional. Uma rejeição local mantém o alerta de vencimento
pendente e registra `administrator_alert_transport_failed` no journal. Investigue
a fila do MTA, repita `--test-alert` e verifique a caixa novamente depois do
reparo. Uma falha persistente do ciclo é reportada em cada execução que falha.

Use `sudo journalctl -u dsm-controller-tls.service` para o código da falha
e verifique a CA, a validade, as permissões, o hostname e o endereço de
bind. O log privado do Certbot fica sob controle do root. Depois de corrigir
uma falha de prontidão, `"${TLSCTL[@]}" --retry` revalida um candidato
rejeitado. A mesma geração rejeitada exige essa ação antes de outra tentativa,
mesmo com timer ativo. O pending journal permite recuperar uma interrupção
em `ExecStopPost` ou no próximo ciclo. Um crash pode manter o candidato
selecionado até a recuperação e um par anterior vencido não restaura HTTPS
verificado. Se o Controller não conseguir iniciar, suspenda o timer, preserve
os artefatos e restaure um par de confiança em janela autorizada. Verifique
HTTPS antes de reabilitar o timer. O rollback do produto continua no
atualizador convencional.
