#!/bin/sh
#
# DSM Universal Runtime
# Filesystem API
#

runtime_path_exists()
{
    local path="$1"

    [ -e "$path" ]
}


runtime_path_directory()
{
    local path="$1"

    [ -d "$path" ]
}


runtime_path_size()
{
    local path="$1"

    du -sh "$path" 2>/dev/null | awk '{print $1}'
}