#!/usr/bin/env bash


process_signal_pid()
{


local SIGNAL="$1"

local PID="$2"



if kill -"${SIGNAL}" "${PID}" 2>/dev/null
then

return 0

fi


return 1


}