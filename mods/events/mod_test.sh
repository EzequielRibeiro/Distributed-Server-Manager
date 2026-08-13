#!/bin/bash

# =============================================================
# DSM Mod Event Test
# Commit 15
# =============================================================


ENGINE="/opt/dsm/mods/events/mod_engine.sh"



case "$1" in


update)

"$ENGINE" test \
"@CF updated successfully"


;;


missing)

"$ENGINE" test \
"@Expansion missing key"


;;


failed)

"$ENGINE" test \
"@Trader update failed"


;;


*)

echo "

Mod Test

Uso:

mod_test.sh update

mod_test.sh missing

mod_test.sh failed

"

;;

esac