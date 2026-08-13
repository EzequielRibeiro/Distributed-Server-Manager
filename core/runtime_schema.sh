#!/usr/bin/env bash
# =============================================================
# DSM Runtime Schema
#
# Define formato padrão dos módulos
# =============================================================


runtime_schema_version()
{
    echo "1.0"
}


runtime_schema_template()
{

cat <<EOF
{
    "module":"",
    "timestamp":"",
    "status":"",
    "health":"",
    "data":{}
}
EOF

}