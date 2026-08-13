#!/bin/bash
# =============================================================
# DSM Discord Integration Engine v1.2.0
#
# Arquivo:
#   core/discord_rate_limit.sh
#
# Função:
#   Controle de frequência de mensagens Discord
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

STATE_DIR="$DSM_ROOT/runtime/discord"
RATE_FILE="$STATE_DIR/rate_limit.json"

# -------------------------------------------------------------
# Configurações
# -------------------------------------------------------------
MIN_INTERVAL=300
# 5 minutos entre alertas iguais

GLOBAL_LIMIT=20
# máximo de mensagens por janela

WINDOW=3600
# janela de 1 hora

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
rate_init()
{
mkdir -p "$STATE_DIR"

if [ ! -f "$RATE_FILE" ]; then
echo "{}" > "$RATE_FILE"
fi
}

# -------------------------------------------------------------
# Timestamp atual
# -------------------------------------------------------------
now()
{
date +%s
}

# -------------------------------------------------------------
# Verificar alerta específico
# -------------------------------------------------------------
check_alert()
{
local id="$1"

rate_init

local current
current=$(now)

local last
last=$(
jq -r \
--arg id "$id" \
'.[$id] // 0' \
"$RATE_FILE"
)

if [ "$last" = "0" ]; then
return 0
fi

local diff
diff=$((current-last))

if [ "$diff" -lt "$MIN_INTERVAL" ]; then
return 1
fi

return 0
}

# -------------------------------------------------------------
# Registrar envio
# -------------------------------------------------------------
mark_sent()
{
local id="$1"

rate_init

local tmp
tmp=$(mktemp)

jq \
--arg id "$id" \
--arg time "$(now)" \
'
.[$id]=$time
' \
"$RATE_FILE" > "$tmp"

mv "$tmp" "$RATE_FILE"
}

# -------------------------------------------------------------
# Controle global
# -------------------------------------------------------------
global_check()
{
local log="$STATE_DIR/send.log"

mkdir -p "$STATE_DIR"
touch "$log"

local current
current=$(now)

local start
start=$((current-WINDOW))

local count
count=$(
awk -v start="$start" '
$1 >= start {count++}
END{
print count+0
}
' "$log"
)

if [ "$count" -ge "$GLOBAL_LIMIT" ]; then
return 1
fi

return 0
}

# -------------------------------------------------------------
# Registrar envio global
# -------------------------------------------------------------
global_mark()
{
mkdir -p "$STATE_DIR"

echo "$(now)" \
>> "$STATE_DIR/send.log"
}

# -------------------------------------------------------------
# Limpeza
# -------------------------------------------------------------
cleanup()
{
local file="$STATE_DIR/send.log"

if [ -f "$file" ]; then
local limit
limit=$(( $(now)-WINDOW ))

awk \
-v limit="$limit" \
'$1 >= limit' \
"$file" \
> "$file.tmp"

mv "$file.tmp" "$file"
fi
}

# -------------------------------------------------------------
# Verificação completa
# -------------------------------------------------------------
allow()
{
local id="$1"

cleanup

if ! check_alert "$id"; then
echo "BLOCKED_ALERT_INTERVAL"
return 1
fi

if ! global_check; then
echo "BLOCKED_GLOBAL_LIMIT"
return 1
fi

mark_sent "$id"
global_mark

echo "ALLOWED"
return 0
}

# -------------------------------------------------------------
# Execução
# -------------------------------------------------------------
case "$1" in

check)
allow "$2"
;;

mark)
mark_sent "$2"
;;

cleanup)
cleanup
;;

stats)
rate_init
cat "$RATE_FILE"
;;

*)
cat <<EOF


DSM Discord Rate Limit v1.2.0


Uso:


Verificar:

 discord_rate_limit.sh check ALERT_ID



Registrar:

 discord_rate_limit.sh mark ALERT_ID



Limpar:

 discord_rate_limit.sh cleanup



Status:

 discord_rate_limit.sh stats



EOF
;;
esac
