# Recuperação de vínculo de um Agent

## Objetivo

Este runbook descreve como recuperar um Agent que continua instalado na máquina remota, mas perdeu o vínculo com o Controller. O caso típico ocorre após perda, restauração ou recriação do banco de dados do Controller: o Agent conserva sua identidade local e a credencial permanente antiga, enquanto o novo banco já não contém essa credencial.

O objetivo é **reenrolar o mesmo Agent**, preservando `agent_id`, `node_id` e `fingerprint`, sem reinstalar o runtime e sem criar uma identidade duplicada.

## Sintomas típicos

No Agent, o serviço pode permanecer `active (running)`, mas os heartbeats são rejeitados:

```text
heartbeat failed: Controller rejected request (401)
{
  "error": "agent_authentication_failed",
  "message": "Identidade do Agent inválida."
}
```

No Controller, o `agent_id` antigo não aparece mais na tabela `agents` ou na Dashboard.

> Um Agent instalado não deve ser considerado perdido apenas porque desapareceu da Dashboard. Primeiro confirme o estado local da máquina remota.

## Princípios de segurança

- Não reinstale o Agent antes de confirmar que a instalação local realmente desapareceu.
- Preserve `agent_id`, `node_id` e `fingerprint` durante a recuperação.
- Pairing tokens são segredos temporários de uso único. Não os publique em tickets, chats, logs ou documentação.
- Não exiba `credential_secret`.
- Faça backup de `/etc/capivara-agent/agent.json` antes de alterar a credencial local.
- O arquivo de identidade deve continuar legível apenas pelo usuário do serviço, normalmente `capivara-agent`, com modo `0600`.
- Prefira a emissão de pairing token pela interface/fluxo administrativo oficial. O procedimento Python abaixo existe como recuperação operacional quando a interface administrativa ainda não oferece a ação de revincular.

## 1. Confirmar que o Agent continua instalado

Execute na máquina remota:

```bash
hostname
hostname -I

systemctl status capivara-agent.service \
  --no-pager \
  --lines=30

sudo journalctl \
  -u capivara-agent.service \
  -n 80 \
  --no-pager \
  -l

ls -la /opt/capivara-agent
```

Se `/opt/capivara-agent` existir e o serviço estiver carregado, prossiga com a recuperação do vínculo em vez de reinstalar.

## 2. Ler a identidade local sem revelar segredos

No Agent:

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path

path = Path("/etc/capivara-agent/agent.json")
data = json.loads(path.read_text())

for key in (
    "controller_url",
    "controller_id",
    "agent_id",
    "node_id",
    "name",
    "advertise_address",
    "fingerprint",
    "credential_id",
    "credential_type",
):
    print(f"{key}: {data.get(key)}")

print("pairing_token:", "<presente>" if data.get("pairing_token") else None)
print("credential_secret:", "<presente>" if data.get("credential_secret") else None)
PY
```

Anote, em local seguro, os valores de:

- `agent_id`
- `node_id`
- `fingerprint`
- `controller_url`

Esses valores identificam a instalação física que será recuperada.

## 3. Confirmar que a identidade não existe no Controller

Em PostgreSQL:

```sql
SELECT id, controller_id, node_id, name, status
FROM agents
ORDER BY id;
```

Antes do reenrollment, os antigos `agent_id` e `node_id` devem estar ausentes. O enrollment seguro rejeita IDs já existentes para impedir colisões de identidade.

Se os IDs ainda existirem, não continue: determine primeiro se existe apenas uma credencial inválida, um registro parcial ou um Agent duplicado.

## 4. Confirmar o Controller ativo

```sql
SELECT id, node_id, name, status
FROM controllers
ORDER BY id;
```

O Controller escolhido para o novo pairing deve estar `active`.

## 5. Emitir um pairing token novo

### Método preferido

Use o fluxo administrativo do Capivara para emissão de pairing token. O token deve ter vida curta e ser usado imediatamente.

### Recuperação operacional via backend

Quando a interface administrativa ainda não disponibilizar a ação de revincular, o token pode ser emitido pelo repositório oficial da aplicação usando o mesmo ambiente do Dashboard.

No Controller:

```bash
cd /opt/dsm

sudo bash -c '
set -a
source /etc/default/dsm-dashboard
set +a

PYTHONPATH=/opt/dsm/database:/opt/dsm/dashboard:/opt/dsm/core \
python3 - <<'"'"'PY'"'"'
from runtime_backend import backend_from_environment
from agent_pairing_repository import AgentPairingRepository

backend = backend_from_environment()

with backend.connect() as connection:
    rows = connection.execute(
        "SELECT id,status FROM controllers ORDER BY id"
    ).fetchall()

active = [dict(row) for row in rows if str(row["status"]).lower() == "active"]
if len(active) != 1:
    raise SystemExit(
        f"Esperado exatamente 1 Controller ativo; encontrados {len(active)}."
    )

controller_id = str(active[0]["id"])
issued = AgentPairingRepository(backend).issue_token(
    controller_id=controller_id,
    created_by="agent-relink-recovery",
    ttl_seconds=900,
)

print("CONTROLLER_ID=" + controller_id)
print("PAIRING_TOKEN=" + issued.token)
print("EXPIRES_AT=" + str(issued.expires_at))
PY
'
```

Não copie o token para locais públicos. Se ele expirar ou for exposto antes do consumo, emita outro.

## 6. Parar o Agent e fazer backup da identidade

No Agent:

```bash
sudo systemctl stop capivara-agent.service

sudo cp \
  /etc/capivara-agent/agent.json \
  /etc/capivara-agent/agent.json.before-reenroll
```

## 7. Substituir somente a credencial órfã

Use entrada silenciosa para evitar exibir o pairing token no terminal:

```bash
read -rsp "Novo pairing token: " PAIRING_TOKEN
echo

sudo env PAIRING_TOKEN="$PAIRING_TOKEN" python3 - <<'PY'
import json
import os
import pwd
import grp
from pathlib import Path

path = Path("/etc/capivara-agent/agent.json")
data = json.loads(path.read_text())

token = os.environ["PAIRING_TOKEN"].strip()
if not token:
    raise SystemExit("Pairing token vazio.")

# Preserve agent_id, node_id, fingerprint, controller_url e toda a configuração local.
data.pop("credential_id", None)
data.pop("credential_secret", None)
data.pop("credential_type", None)
data.pop("controller_id", None)
data["pairing_token"] = token

tmp = path.with_suffix(".tmp")
tmp.write_text(
    json.dumps(data, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

uid = pwd.getpwnam("capivara-agent").pw_uid
gid = grp.getgrnam("capivara-agent").gr_gid
os.chown(tmp, uid, gid)
os.chmod(tmp, 0o600)
tmp.replace(path)
os.chown(path, uid, gid)
os.chmod(path, 0o600)

print("Identidade preparada para reenrollment.")
print("agent_id:", data.get("agent_id"))
print("node_id:", data.get("node_id"))
print("fingerprint:", data.get("fingerprint"))
PY

unset PAIRING_TOKEN
```

## 8. Validar permissões antes de iniciar

```bash
sudo ls -l /etc/capivara-agent/agent.json

sudo -u capivara-agent python3 - <<'PY'
from pathlib import Path
p = Path("/etc/capivara-agent/agent.json")
print("readable:", p.is_file())
print("bytes:", len(p.read_bytes()))
PY
```

O arquivo deve pertencer ao usuário/grupo do serviço e ser legível por ele. Um erro como:

```text
PermissionError: [Errno 13] Permission denied: '/etc/capivara-agent/agent.json'
```

indica propriedade ou modo incorretos, não falha de pairing.

## 9. Iniciar e validar o reenrollment

```bash
sudo systemctl start capivara-agent.service
sleep 5

systemctl status capivara-agent.service \
  --no-pager \
  --lines=20

sudo journalctl \
  -u capivara-agent.service \
  --since "-1 minute" \
  --no-pager \
  -l
```

O resultado esperado após o enrollment é:

```text
heartbeat ok agent=<agent_id> health=online status=active
```

## 10. Confirmar que o token foi consumido e uma credencial permanente foi criada

No Agent:

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("/etc/capivara-agent/agent.json").read_text())
print("controller_id:", data.get("controller_id"))
print("pairing_token:", "<presente>" if data.get("pairing_token") else None)
print("credential_id:", data.get("credential_id"))
print("credential_secret:", "<presente>" if data.get("credential_secret") else None)
PY
```

Após sucesso:

- `pairing_token` deve ser `None`/ausente;
- `credential_id` deve existir;
- `credential_secret` deve existir, mas nunca deve ser exibido.

## 11. Validar o lado do Controller

Em PostgreSQL:

```sql
SELECT id, controller_id, node_id, name, status, created_at, updated_at
FROM agents
WHERE id = '<AGENT_ID>';

SELECT agent_id, hostname, address, fingerprint, updated_at
FROM agent_runtime_inventory
WHERE agent_id = '<AGENT_ID>';

SELECT id, agent_id, controller_id, credential_type, revoked_at
FROM agent_credentials
WHERE agent_id = '<AGENT_ID>';
```

O Agent deve estar `active`, o fingerprint deve ser o mesmo da instalação preservada e a credencial nova deve estar sem `revoked_at`.

## 12. Executar o Doctor local

Depois do reenrollment, execute no Agent:

```bash
cap agent doctor
```

Para saída estruturada:

```bash
cap agent doctor --json
```

O Doctor existente verifica identidade/enrollment, serviço, conectividade ao Controller, recursos do host, capabilities, faixas de portas, conflitos de sockets, game-data, SteamCMD quando aplicável e estado recente de atualização.

## Falhas comuns

### `agent_authentication_failed`

A credencial permanente do Agent não existe mais ou não corresponde ao banco atual. Faça reenrollment.

### `pairing_rejected`

O token é inválido, expirou ou já foi consumido. Pare o serviço, emita outro token e repita apenas a troca de credencial.

### `pairing_conflict`

O `agent_id` ou `node_id` já existe no Controller. Não crie uma segunda identidade. Investigue o registro existente.

### `PermissionError` em `agent.json`

Corrija proprietário/grupo e modo do arquivo antes de tentar novamente. O serviço normalmente roda como `capivara-agent` e precisa conseguir ler e regravar a identidade durante o enrollment.

### Agent online, mas sem endereço no inventário

Verifique `advertise_address` em `/etc/capivara-agent/agent.json`. Heartbeat e autenticação podem funcionar sem esse valor, mas placement, inventário e operação distribuída podem precisar de um endereço anunciado válido.

## Estado final esperado

Uma recuperação está concluída somente quando todos os itens abaixo forem verdadeiros:

- serviço `capivara-agent.service` ativo;
- heartbeat aceito pelo Controller;
- `status=active` no Controller;
- `agent_id`, `node_id` e `fingerprint` preservados;
- pairing token removido após consumo;
- nova credencial permanente registrada e não revogada;
- runtime inventory atualizado;
- `cap agent doctor` sem findings críticos.

## Evolução planejada

O procedimento manual deste runbook deve permanecer como recuperação de emergência. A operação normal deverá ser oferecida pela Dashboard administrativa através de uma ação **Revincular Agent**, integrada ao pairing seguro, rotação de credencial, diagnóstico remoto e trilha de auditoria.
