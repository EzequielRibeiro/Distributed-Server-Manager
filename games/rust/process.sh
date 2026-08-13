#!/bin/bash

GAME_PROCESS="RustDedicated"


game_process()
{
    echo "${GAME_PROCESS}"
}


game_process_command()
{
    echo "./RustDedicated"
}


export -f game_process
export -f game_process_command