#!/bin/bash
# =============================================================
# DSM Discord Integration Engine v1.2.0
#
# Arquivo:
#   core/discord_test.sh
#
# Função:
#   Diagnóstico completo Discord
#
# =============================================================

DSM_ROOT="${DSM_ROOT:-/opt/dsm}"

CONFIG="$DSM_ROOT/config/discord_config.sh"
WEBHOOK="$DSM_ROOT/core/discord_webhook.sh"
QUEUE="$DSM_ROOT/core/discord_queue.sh"

LOG="$DSM_ROOT/logs/discord_test.log"

# -------------------------------------------------------------
# Inicialização
# -------------------------------------------------------------
init()
{
mkdir -p "$(dirname "$LOG")"
touch "$LOG"
}

# -------------------------------------------------------------
# Log
# -------------------------------------------------------------
log()
{
echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" \
>> "$LOG"
}

# -------------------------------------------------------------
# Resultado
# -------------------------------------------------------------
ok()
{
echo "[ OK ] $1"
log "OK - $1"
}

fail()
{
echo "[FAIL] $1"
log "FAIL - $1"
}

# -------------------------------------------------------------
# Testar configuração
# -------------------------------------------------------------
test_config()
{
echo ""
echo "Teste de configuração Discord"
echo "------------------------------"

if [ ! -f "$CONFIG" ]; then
    fail "discord_config.sh inexistente"
    return 1
fi

source "$CONFIG"

if discord_init; then
    ok "Configuração carregada"
else
    fail "Configuração inválida"
    return 1
fi
}

# -------------------------------------------------------------
# Testar dependências
# -------------------------------------------------------------
test_dependencies()
{
echo ""
echo "Teste de dependências"
echo "---------------------"

for cmd in curl jq uuidgen
do
if command -v "$cmd" >/dev/null
then
    ok "$cmd instalado"
else
    fail "$cmd ausente"
fi
done
}

# -------------------------------------------------------------
# Testar webhook
# -------------------------------------------------------------
test_webhook()
{
echo ""
echo "Teste Webhook"
echo "-------------"

if "$WEBHOOK" test
then
    ok "Webhook respondeu"
else
    fail "Falha no webhook"
fi
}

# -------------------------------------------------------------
# Testar Embed
# -------------------------------------------------------------
test_embed()
{
echo ""
echo "Teste Embed Discord"
echo "-------------------"

JSON=$(
jq -n '
{
embeds:[
{
title:"DSM TEST",
description:"Teste Embed funcionando",
color:5763719
}
]
}
'
)

if "$WEBHOOK" embed "$JSON"
then
    ok "Embed enviado"
else
    fail "Falha Embed"
fi
}

# -------------------------------------------------------------
# Testar fila
# -------------------------------------------------------------
test_queue()
{
echo ""
echo "Teste fila"
echo "----------"

"$QUEUE" add \
TEST \
"Mensagem teste DSM"

RESULT=$(
"$QUEUE" stats
)

echo "$RESULT"

ok "Fila operacional"
}

# -------------------------------------------------------------
# Relatório
# -------------------------------------------------------------
report()
{
echo ""
echo "================================"
echo " DSM DISCORD TEST REPORT"
echo "================================"

echo ""
echo "Servidor:"
hostname

echo ""
echo "Data:"
date

echo ""
echo "Log:"
echo "$LOG"

echo ""
}

# -------------------------------------------------------------
# Execução completa
# -------------------------------------------------------------
full_test()
{
test_dependencies
test_config
test_webhook
test_embed
test_queue
report
}

# -------------------------------------------------------------
# Execução
# -------------------------------------------------------------
init

case "$1" in

config)
test_config
;;

webhook)
test_webhook
;;

embed)
test_embed
;;

queue)
test_queue
;;

all)
full_test
;;

*)
cat <<EOF


DSM Discord Test v1.2.0


Uso:


Teste configuração:

 discord_test.sh config



Teste webhook:

 discord_test.sh webhook



Teste embed:

 discord_test.sh embed



Teste fila:

 discord_test.sh queue



Teste completo:

 discord_test.sh all



EOF
;;
esac
