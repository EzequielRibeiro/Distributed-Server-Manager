#!/bin/bash
# =============================================================
# doctor/runner.sh
#
# Doctor Independent Runner
#
# Responsável por executar diagnóstico DSM
#
# =============================================================


DSM_ROOT="${DSM_ROOT:-/opt/dsm}"


# =============================================================
# Bootstrap
# =============================================================

if ! declare -F log_info >/dev/null
then
    source "${DSM_ROOT}/core/bootstrap.sh"
fi

# =============================================================
# Doctor
# =============================================================

source "${DSM_ROOT}/doctor/doctor.sh"


# =============================================================
# Execução
# =============================================================


doctor_run

RESULT=$?


echo

echo "================================================="
echo " DSM Doctor"
echo "================================================="

echo

echo "Score:"
echo "${DOCTOR_SCORE}/${DOCTOR_MAX}"


echo

echo "Status:"

if [[ "${RESULT}" -eq 0 ]]
then
    echo "HEALTHY"
else
    echo "WARNING"
fi


echo

echo "Relatório:"
echo


doctor_format_report


exit "${RESULT}"