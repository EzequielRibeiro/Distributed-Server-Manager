#!/usr/bin/env bash
DSM_ROOT="${DSM_ROOT:-/opt/dsm}"
exec "$DSM_ROOT/core/user_manager.sh" "$@"
