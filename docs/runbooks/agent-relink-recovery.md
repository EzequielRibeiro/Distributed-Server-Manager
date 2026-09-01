# Recuperação e revinculação de um Agent

## Objetivo

Este runbook descreve como recuperar um Capivara Agent que continua instalado no host remoto, mas perdeu a capacidade de autenticar no Controller ou teve sua identidade local persistida recriada/incorretamente alterada.

O objetivo é recuperar o **mesmo Agent lógico**, preservando sempre que possível `agent_id`, `node_id`, `fingerprint` e o vínculo físico `host_identity`, sem reinstalar o runtime e sem criar um Agent duplicado.

O fluxo normal de recuperação usa a funcionalidade administrativa já disponível na Dashboard:

```text
Agent
→ Administração e manutenção
→ Credencial e revinculação
→ Preparar revinculação
```

O Controller gera um token de uso único e o Agent executa `relink_cli.py` para substituir a credencial perdida por uma nova credencial permanente.

## Cenários cobertos

Antes de executar qualquer correção, identifique em qual cenário o host se encontra.

### Cenário A — Agent registrado, identidade local correta e credencial perdida

O Agent ainda existe no Controller com o mesmo `agent_id`, `node_id` e `fingerprint`, mas o arquivo local não possui uma credencial utilizável ou os heartbeats recebem `401`.

Fluxo recomendado:

```text
parar serviço
→ backup do agent.json
→ preparar revinculação na Dashboard
→ executar relink_cli.py
→ reiniciar serviço
→ validar heartbeat
```

### Cenário B — Agent registrado, mas `agent.json` foi recriado ou contém identidade lógica incorreta

O host físico continua sendo o mesmo e o Controller ainda possui o Agent correto, porém `/etc/capivara-agent/agent.json` contém outro `agent_id`, outro `node_id`, outro `fingerprint`, ausência de `credential_id`/`credential_secret` ou um `pairing_token` antigo.

Neste cenário, **não execute o relink diretamente**. O endpoint de relink valida `agent_id`, `node_id` e `fingerprint`; valores locais divergentes resultarão em `relink_rejected`.

Fluxo recomendado:

```text
identificar o Agent lógico correto no Controller
→ confirmar host_identity
→ parar serviço
→ backup do agent.json
→ restaurar apenas agent_id/node_id/fingerprint históricos
→ preparar revinculação na Dashboard
→ executar relink_cli.py
→ reiniciar serviço
→ validar heartbeat
```

### Cenário C — Agent ausente do Controller após perda/restauração do banco

O Agent conserva sua identidade local, mas o registro correspondente não existe mais no banco atual do Controller.

Este é um fluxo excepcional de recuperação/reenrollment. Não use o procedimento do Cenário A ou B sem primeiro confirmar que `agent_id` e `node_id` realmente estão ausentes do Controller.

## Distinção importante: `host_identity` não é `fingerprint`

O Capivara mantém dois conceitos diferentes:

- `host_identity`: identifica o host físico e é vinculado ao Agent no Controller;
- `fingerprint`: identifica a identidade lógica/autenticável apresentada pelo Agent e é armazenado no runtime inventory e nas credenciais.

Um `host_identity` correto não significa que o `fingerprint` local também esteja correto.

Não use **Revincular identidade física** para corrigir perda de credencial ou `agent.json` recriado quando o host físico continua sendo o mesmo. O rebind de host identity é destinado a troca real de host, clone controlado ou regeneração intencional da identidade física.

## Princípios de segurança

- Não reinstale o Agent antes de confirmar que a instalação local realmente desapareceu.
- Não crie um novo Agent apenas porque o host está offline.
- Faça backup de `/etc/capivara-agent/agent.json` antes de qualquer alteração.
- Nunca exiba `credential_secret`.
- Tokens de relink/pairing são segredos temporários de uso único. Não os publique em tickets, chats, documentação ou logs.
- Não coloque o token diretamente na linha de comando se isso puder gravá-lo no histórico do shell; prefira entrada silenciosa com `read -rsp`.
- O `agent.json` deve permanecer sob propriedade do usuário do serviço, normalmente `capivara-agent`, com modo `0600`.
- Não altere `host_identity` sem evidência de mudança física real do host.
- Não execute reinstalação, remoção ou pairing genérico enquanto ainda for possível recuperar o Agent lógico existente.

## 1. Confirmar que o Agent continua instalado

No host remoto:

```bash
hostname
hostname -I

sudo systemctl status capivara-agent.service \
  --no-pager \
  --lines=30

sudo journalctl \
  -u capivara-agent.service \
  -n 100 \
  --no-pager \
  -l

sudo ls -la /opt/capivara-agent
```

Se `/opt/capivara-agent` existir e o serviço estiver carregado, prossiga com recuperação em vez de reinstalação.

Sintomas comuns incluem:

```text
heartbeat failed: Controller rejected request (401)
```

ou:

```text
pairing_rejected
Pareamento inválido ou expirado.
```

ou um loop de restart em que o runtime tenta `enroll()` por não encontrar `credential_id`/`credential_secret`.

## 2. Ler a identidade local sem revelar segredos

No Agent:

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path

path = Path("/etc/capivara-agent/agent.json")
data = json.loads(path.read_text(encoding="utf-8"))

for key in (
    "controller_url",
    "controller_id",
    "agent_id",
    "node_id",
    "hostname",
    "fingerprint",
    "capivara_version",
):
    print(f"{key}: {data.get(key)}")

for key in (
    "credential_id",
    "credential_secret",
    "pairing_token",
):
    value = data.get(key)
    print(f"{key}: present={bool(value)} length={len(str(value)) if value else 0}")
PY
```

Não copie valores secretos. Para diagnóstico, apenas presença/ausência é suficiente.

## 3. Ler o `host_identity` físico

No Agent:

```bash
sudo cat /var/lib/capivara-agent/host-identity
```

Formato esperado:

```text
sha256:<64 caracteres hexadecimais>
```

Esse valor será usado para confirmar qual Agent lógico pertence ao host físico.

## 4. Identificar o Agent correto no Controller

Quando o `agent.json` local estiver suspeito, não confie somente no `agent_id` presente nele.

No Controller, use `agent_runtime_inventory` para cruzar hostname e fingerprint histórico:

```sql
SELECT
    agent_id,
    hostname,
    os_name,
    architecture,
    capivara_version,
    fingerprint,
    health_status,
    last_seen,
    updated_at
FROM agent_runtime_inventory
ORDER BY agent_id;
```

Depois confirme o binding físico do Agent identificado:

```bash
cap agent identity show <AGENT_ID> --json
```

Se estiver usando diretamente o CLI Python no Controller:

```bash
python3 database/agent_identity_cli.py \
  show \
  <AGENT_ID> \
  --json
```

O `host_identity` retornado deve corresponder a `/var/lib/capivara-agent/host-identity` do host remoto.

Se corresponder, **não faça host identity rebind**.

## 5. Confirmar fingerprint histórico e credencial ativa

No Controller, confirme que o fingerprint do inventário corresponde ao fingerprint da credencial ativa:

```sql
SELECT agent_id, hostname, fingerprint
FROM agent_runtime_inventory
WHERE agent_id = '<AGENT_ID>';

SELECT id, agent_id, fingerprint, status, issued_at, last_used_at, revoked_at
FROM agent_credentials
WHERE agent_id = '<AGENT_ID>'
ORDER BY issued_at DESC;
```

Para o Cenário B, o fingerprint histórico retornado pelo Controller é o valor que deve ser restaurado no `agent.json` antes do relink.

## 6. Parar o serviço e fazer backup

No Agent:

```bash
sudo systemctl stop capivara-agent.service

STAMP="$(date +%Y%m%d-%H%M%S)"

sudo cp -a \
  /etc/capivara-agent/agent.json \
  "/etc/capivara-agent/agent.json.before-relink-${STAMP}"

sudo systemctl is-active capivara-agent.service || true
```

O serviço deve permanecer `inactive` durante a preparação.

## 7. Cenário A — identidade correta, credencial perdida

Se `agent_id`, `node_id` e `fingerprint` locais já correspondem ao Controller, não altere esses campos.

Prossiga diretamente para **Preparar revinculação** na Dashboard.

## 8. Cenário B — restaurar somente a identidade lógica histórica

Use esta etapa somente depois de identificar com segurança o Agent correto e seu fingerprint histórico.

No Agent, altere apenas:

- `agent_id`;
- `node_id`;
- `fingerprint`.

Exemplo:

```bash
sudo python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path("/etc/capivara-agent/agent.json")
data = json.loads(path.read_text(encoding="utf-8"))

# Substitua pelos valores históricos confirmados no Controller.
data["agent_id"] = "<AGENT_ID>"
data["node_id"] = "<NODE_ID>"
data["fingerprint"] = "<FINGERPRINT_HISTORICO>"

tmp = path.with_suffix(".identity-repair.tmp")
tmp.write_text(
    json.dumps(data, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

stat = path.stat()
os.chmod(tmp, 0o600)
os.chown(tmp, stat.st_uid, stat.st_gid)
os.replace(tmp, path)

print("IDENTITY_REPAIR_OK")
print("agent_id:", data.get("agent_id"))
print("node_id:", data.get("node_id"))
print("fingerprint:", data.get("fingerprint"))
print("credential_id_present:", bool(data.get("credential_id")))
print("credential_secret_present:", bool(data.get("credential_secret")))
print("pairing_token_present:", bool(data.get("pairing_token")))
PY
```

Não restaure `credential_secret` manualmente. O Controller armazena hash do segredo, não o segredo em texto claro; a credencial antiga não deve ser reconstruída.

## 9. Preparar revinculação na Dashboard

No Controller:

```text
Agent
→ Administração e manutenção
→ Credencial e revinculação
→ Preparar revinculação
```

A ação chama o endpoint administrativo:

```text
POST /api/admin/agent/relink/prepare
```

O token é associado ao Agent selecionado, tem vida curta e é exibido uma única vez.

A operação de relink preserva:

- `agent_id`;
- `node_id`;
- `fingerprint`;
- vínculo físico do Agent.

E cria uma nova credencial permanente, revogando a anterior ativa.

## 10. Executar o relink no Agent sem expor o token

No Agent:

```bash
read -rsp 'Token de relink: ' RELINK_TOKEN
echo

sudo -u capivara-agent \
  python3 /opt/capivara-agent/runtime/relink_cli.py \
  --token "$RELINK_TOKEN"

RC=$?
unset RELINK_TOKEN

echo "relink_exit_code=$RC"
```

Resultado esperado:

```text
RELINK_OK: restart capivara-agent.service and wait for the next heartbeat
relink_exit_code=0
```

O `relink_cli.py`:

- envia `agent_id`, `node_id` e `fingerprint` ao Controller;
- recebe nova `credential_id` e `credential_secret`;
- grava a nova credencial em `/etc/capivara-agent/agent.json`;
- remove `pairing_token`;
- preserva propriedade e modo do arquivo.

Se o relink retornar erro, **não reinicie o serviço ainda**. Corrija primeiro a causa.

## 11. Reiniciar e validar heartbeat

Somente após `relink_exit_code=0`:

```bash
sudo systemctl restart capivara-agent.service

sleep 5

sudo systemctl status capivara-agent.service \
  --no-pager \
  -l

sudo journalctl \
  -u capivara-agent.service \
  --since "2 minutes ago" \
  --no-pager \
  -n 120
```

Resultado esperado:

```text
heartbeat ok agent=<AGENT_ID> health=online status=active
```

Não devem aparecer novos eventos `pairing_rejected`, `relink_rejected` ou `agent_authentication_failed`.

## 12. Confirmar o estado seguro do `agent.json`

No Agent:

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path

p = Path("/etc/capivara-agent/agent.json")
d = json.loads(p.read_text(encoding="utf-8"))

print("agent_id:", d.get("agent_id"))
print("node_id:", d.get("node_id"))
print("controller_id:", d.get("controller_id"))
print("credential_id_present:", bool(d.get("credential_id")))
print("credential_secret_present:", bool(d.get("credential_secret")))
print("pairing_token_present:", bool(d.get("pairing_token")))
PY
```

Após sucesso:

```text
credential_id_present: True
credential_secret_present: True
pairing_token_present: False
```

Nunca exiba o conteúdo de `credential_secret`.

## 13. Validar o Controller

Confirme que o Agent voltou a atualizar inventário e que a nova credencial está ativa:

```sql
SELECT id, controller_id, node_id, name, status, updated_at
FROM agents
WHERE id = '<AGENT_ID>';

SELECT
    agent_id,
    hostname,
    fingerprint,
    capivara_version,
    health_status,
    last_seen,
    updated_at
FROM agent_runtime_inventory
WHERE agent_id = '<AGENT_ID>';

SELECT
    id,
    agent_id,
    credential_type,
    status,
    issued_at,
    last_used_at,
    revoked_at
FROM agent_credentials
WHERE agent_id = '<AGENT_ID>'
ORDER BY issued_at DESC;
```

O esperado é:

- Agent `active`;
- inventário recente;
- heartbeat atualizado;
- uma credencial nova `active`;
- credencial anterior `revoked`.

## 14. Executar o Doctor local

Depois da recuperação:

```bash
cap agent doctor
```

Para saída estruturada:

```bash
cap agent doctor --json
```

O Doctor verifica identidade/enrollment, serviço, conectividade com o Controller, recursos do host, capabilities, portas, game-data, SteamCMD quando aplicável e estado recente de atualização.

## Cenário C — registro realmente ausente do Controller

Use esta seção apenas quando o Agent não existir mais no Controller e a identidade local preservada tiver sido validada.

Nesse caso, o fluxo de reenrollment é diferente do relink administrativo porque não existe um Agent lógico registrado para receber um token de relink vinculado.

Antes de reenrolar:

```sql
SELECT id, controller_id, node_id, name, status
FROM agents
ORDER BY id;
```

Confirme que `agent_id` e `node_id` realmente estão ausentes.

Se os IDs ainda existirem, volte para o Cenário A ou B. Não crie uma segunda identidade.

A recuperação por pairing genérico deve ser considerada **fallback operacional** para perda/restauração do banco, não o método normal para perda de credencial.

## Falhas comuns

### `relink_rejected`

O token expirou, já foi consumido, não foi preparado para aquele Agent ou `agent_id`/`node_id`/`fingerprint` apresentados pelo host não correspondem ao Controller.

No Cenário B, confirme principalmente se o `agent.json` foi reparado com a identidade histórica antes de repetir o relink.

### `pairing_rejected`

O Agent entrou no fluxo normal de enrollment porque não possui credencial persistente e está usando um `pairing_token` inválido, expirado ou já consumido.

Para Agent que ainda existe no Controller, não tente resolver isso gerando outro Agent. Pare o serviço e use o fluxo administrativo de relink.

### `agent_authentication_failed`

A credencial apresentada não existe, está revogada ou não corresponde ao Agent registrado. Use revinculação administrativa quando o Agent lógico ainda existir.

### `pairing_conflict`

O `agent_id` ou `node_id` já existe no Controller. Não crie uma segunda identidade. Investigue o registro existente e use relink.

### `PermissionError` em `agent.json`

Corrija proprietário/grupo e modo do arquivo. O serviço normalmente roda como `capivara-agent` e precisa conseguir ler e regravar a configuração.

### Serviço em restart loop

Pare o serviço antes de investigar:

```bash
sudo systemctl stop capivara-agent.service
```

Um restart contínuo pode consumir logs, repetir requests inválidos e dificultar a análise da identidade persistida.

### `host_identity` correto, mas fingerprint diferente

Não faça host identity rebind automaticamente. Isso indica que o host físico pode estar correto enquanto a identidade lógica persistida foi recriada. Identifique o fingerprint histórico no Controller e use o Cenário B.

### Agent online, mas sem endereço no inventário

Verifique `advertise_address` ou a configuração de rede correspondente em `/etc/capivara-agent/agent.json`. Autenticação pode funcionar mesmo sem endereço anunciado, mas placement e operação distribuída podem depender dele.

## Estado final esperado

Uma recuperação está concluída somente quando todos os itens abaixo forem verdadeiros:

- `capivara-agent.service` está `active (running)`;
- heartbeat é aceito pelo Controller;
- Agent está `status=active`;
- `agent_id`, `node_id` e `fingerprint` correspondem ao registro histórico correto;
- `host_identity` continua associado ao host físico correto;
- `credential_id` está presente;
- `credential_secret` está presente, mas nunca foi exibido;
- `pairing_token` foi removido após o relink;
- credencial anterior foi revogada e a nova está ativa;
- runtime inventory foi atualizado;
- `cap agent doctor` não apresenta findings críticos.

## Observação sobre atualização do Agent

Uma atualização de runtime pode reiniciar o serviço e, com isso, fazer o Agent reler um `agent.json` persistido que já estava inconsistente. Nessa situação, a atualização pode **revelar** o problema de identidade sem necessariamente ter sido a causa da corrupção do arquivo.

Por isso, antes de considerar um rollout concluído, o fluxo de atualização deve validar um heartbeat pós-update do Agent. O simples fato de o serviço ter ficado momentaneamente `active` não comprova que a credencial persistida continua utilizável.

## Procedimento de emergência

A manipulação manual de pairing token ou reenrollment deve permanecer reservada a cenários de perda do banco/registro em que o Agent lógico realmente não exista mais no Controller.

Para Agents já registrados, use preferencialmente:

```text
Dashboard administrativa
→ Credencial e revinculação
→ Preparar revinculação
→ relink_cli.py
```

Esse é o fluxo oficial para rotação segura de credencial sem criação de identidade duplicada.
