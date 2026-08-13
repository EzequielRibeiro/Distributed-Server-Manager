#!/usr/bin/env bash


process_status()
{


PID="$(process_pid)"



if [[ -z "${PID}" ]]
then

echo "OFFLINE"

return

fi



if process_pid_validate "${PID}"
then


echo "ONLINE"

echo

echo "PID:"
echo "${PID}"


else


echo "OFFLINE"


fi


}