#!/bin/sh
#
# DSM Universal Runtime
# Logs API
#

runtime_log_directory()
{
    runtime_get directories logs
}


runtime_log_provider()
{
    runtime_get events provider
}


runtime_log_exists()
{
    local dir

    dir=$(runtime_log_directory)

    [ -d "$dir" ]
}