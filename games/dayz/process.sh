#!/usr/bin/env bash

# =============================================================
# DSM Game Adapter
#
# DayZ
#
# Responsável:
# Informar processo principal do jogo
#
# =============================================================


game_process_command()
{
    echo "./DayZServer"
}


export -f game_process_command