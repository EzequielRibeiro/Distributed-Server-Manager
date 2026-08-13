#!/bin/sh
#
# DSM Universal Runtime
# Backup API
#

runtime_backup_directory()
{
    runtime_get directories backup
}


runtime_backup_enabled()
{
    runtime_get features backup
}


runtime_backup_target()
{
    runtime_driver_call driver_backup
}