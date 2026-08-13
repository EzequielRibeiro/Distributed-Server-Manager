#!/bin/sh
#
# ==============================================================================
# DSM Universal Event Normalizer
# Commit 14
#
# Converte eventos DSM para formato Runtime
# ==============================================================================


normalize()
{

TYPE="$1"
CATEGORY="$2"
SOURCE="$3"
MESSAGE="$4"


TIMESTAMP=$(date +%s)



cat <<EOF
{
    "id": "evt-$(date +%s%N)",
    "type": "$TYPE",
    "category": "$CATEGORY",
    "severity": "INFO",
    "source": "$SOURCE",
    "timestamp": $TIMESTAMP,
    "data": {
        "message": "$MESSAGE"
    }
}
EOF

}



#
# Entrada atual do event_manager
#

if [ "$#" -ge 4 ]
then

normalize \
"$1" \
"$2" \
"$3" \
"$4"


exit 0

fi



#
# Compatibilidade antiga
#

SOURCE="$1"
ACTION="$2"


case "$SOURCE:$ACTION" in


monitor:crash)

normalize \
SERVER_CRASH \
server \
DSM \
"Servidor sofreu crash"

;;



monitor:start)

normalize \
SERVER_START \
server \
DSM \
"Servidor iniciado"

;;



backup:create)

normalize \
BACKUP_CREATED \
backup \
DSM \
"Backup criado"

;;



update:finish)

normalize \
UPDATE_FINISHED \
update \
DSM \
"Atualização concluída"

;;



*)

normalize \
UNKNOWN_EVENT \
system \
DSM \
"Evento desconhecido"

;;


esac