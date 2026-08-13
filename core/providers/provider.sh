#!/bin/bash

# =============================================================
# DSM Provider Interface
#
# Contrato comum para todos os providers
# =============================================================


provider_start()
{
    echo "provider_start não implementado."
    return 1
}


provider_stop()
{
    echo "provider_stop não implementado."
    return 1
}


provider_restart()
{
    provider_stop

    sleep 2

    provider_start
}


provider_status()
{
    echo "UNKNOWN"
}


provider_pid()
{
    echo ""
}


provider_logs()
{
    echo "Logs não disponíveis."
}


provider_health()
{
    echo "UNKNOWN"
}