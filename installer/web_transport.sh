#!/usr/bin/env bash
# Controller/Dashboard HTTP(S) installation policy.
# Sourced by install.sh. No side effects until the exported functions are called.

web_transport_is_interactive(){ [[ "${DSM_NON_INTERACTIVE:-0}" != "1" && -t 0 && -t 1 ]]; }
web_transport_die(){ printf '[Capivara][ERRO] %s\n' "$*" >&2; return 1; }
web_transport_validate_port(){ local value="$1"; [[ "${value}" =~ ^[0-9]+$ ]] && (( value >= 1 && value <= 65535 )); }
web_transport_write_config_value(){
    local config="$1" key="$2" value="$3"
    python3 - "$config" "$key" "$value" <<'PY'
from pathlib import Path
import re,sys
path=Path(sys.argv[1]); key=sys.argv[2]; value=sys.argv[3]
text=path.read_text(encoding='utf-8') if path.exists() else ''
quoted='"'+value.replace('\\','\\\\').replace('"','\\"')+'"'; line=f'{key}={quoted}'
pattern=re.compile(rf'(?m)^{re.escape(key)}=.*$')
if pattern.search(text): text=pattern.sub(line,text)
else:
    if text and not text.endswith('\n'): text+='\n'
    text+=line+'\n'
path.write_text(text,encoding='utf-8')
PY
}

web_transport_public_url(){
    local scheme="${DSM_WEB_SCHEME:-http}" host="${DSM_PUBLIC_HOST:-}" port="${DSM_PUBLIC_PORT:-${DSM_WEB_PORT:-}}"
    [[ -n "${host}" ]] || { printf ''; return 0; }
    printf '%s://%s:%s' "${scheme}" "${host}" "${port}"
}

web_transport_select_acme_challenge(){
    DSM_TLS_ACME_CHALLENGE="${DSM_TLS_ACME_CHALLENGE:-}"
    DSM_TLS_DNS_AUTH_HOOK="${DSM_TLS_DNS_AUTH_HOOK:-}"
    DSM_TLS_DNS_CLEANUP_HOOK="${DSM_TLS_DNS_CLEANUP_HOOK:-}"

    if [[ -z "${DSM_TLS_ACME_CHALLENGE}" ]]; then
        if web_transport_is_interactive; then
            printf '\nValidação ACME / Let\x27s Encrypt:\n'
            printf '  1) HTTP-01       - exige porta pública TCP/80 acessível\n'
            printf '  2) DNS-01 manual - funciona com qualquer DNS que permita registro TXT\n'
            printf '  3) DNS-01 hook   - automatizado por scripts externos, sem dependência de provedor\n\n'
            local challenge_answer
            read -r -p 'Validação [1]: ' challenge_answer
            case "${challenge_answer:-1}" in
                1|http|http-01) DSM_TLS_ACME_CHALLENGE=http-01 ;;
                2|dns|dns-manual|dns-01-manual) DSM_TLS_ACME_CHALLENGE=dns-01-manual ;;
                3|dns-hook|dns-01-hook) DSM_TLS_ACME_CHALLENGE=dns-01-hook ;;
                *) web_transport_die "Método ACME inválido: ${challenge_answer}" || return 1 ;;
            esac
        else
            DSM_TLS_ACME_CHALLENGE=http-01
        fi
    fi

    DSM_TLS_ACME_CHALLENGE="${DSM_TLS_ACME_CHALLENGE,,}"
    case "${DSM_TLS_ACME_CHALLENGE}" in
        http|http-01) DSM_TLS_ACME_CHALLENGE=http-01 ;;
        dns|dns-manual|dns-01-manual) DSM_TLS_ACME_CHALLENGE=dns-01-manual ;;
        dns-hook|dns-01-hook) DSM_TLS_ACME_CHALLENGE=dns-01-hook ;;
        *) web_transport_die "DSM_TLS_ACME_CHALLENGE inválido: ${DSM_TLS_ACME_CHALLENGE}" || return 1 ;;
    esac

    if [[ "${DSM_TLS_ACME_CHALLENGE}" == dns-01-hook ]]; then
        if web_transport_is_interactive; then
            local value
            read -r -p "Hook de autenticação DNS [${DSM_TLS_DNS_AUTH_HOOK:-}]: " value
            DSM_TLS_DNS_AUTH_HOOK="${value:-${DSM_TLS_DNS_AUTH_HOOK}}"
            read -r -p "Hook de limpeza DNS [${DSM_TLS_DNS_CLEANUP_HOOK:-}]: " value
            DSM_TLS_DNS_CLEANUP_HOOK="${value:-${DSM_TLS_DNS_CLEANUP_HOOK}}"
        fi
        [[ -n "${DSM_TLS_DNS_AUTH_HOOK}" && -n "${DSM_TLS_DNS_CLEANUP_HOOK}" ]] || {
            web_transport_die "DNS-01 hook exige DSM_TLS_DNS_AUTH_HOOK e DSM_TLS_DNS_CLEANUP_HOOK" || return 1
        }
        [[ -x "${DSM_TLS_DNS_AUTH_HOOK}" ]] || { web_transport_die "Hook de autenticação DNS não é executável: ${DSM_TLS_DNS_AUTH_HOOK}" || return 1; }
        [[ -x "${DSM_TLS_DNS_CLEANUP_HOOK}" ]] || { web_transport_die "Hook de limpeza DNS não é executável: ${DSM_TLS_DNS_CLEANUP_HOOK}" || return 1; }
    fi
}

select_web_transport(){
    case "${DSM_NODE_ROLE:-}" in controller|hybrid) ;; *) return 0 ;; esac
    DSM_WEB_SCHEME="${DSM_WEB_SCHEME:-}"; DSM_WEB_HOST="${DSM_WEB_HOST:-0.0.0.0}"; DSM_WEB_PORT="${DSM_WEB_PORT:-}"
    DSM_PUBLIC_HOST="${DSM_PUBLIC_HOST:-}"; DSM_PUBLIC_PORT="${DSM_PUBLIC_PORT:-}"; DSM_CONTROLLER_PUBLIC_URL="${DSM_CONTROLLER_PUBLIC_URL:-}"
    DSM_TLS_CERT_MODE="${DSM_TLS_CERT_MODE:-}"; DSM_TLS_ACME_CHALLENGE="${DSM_TLS_ACME_CHALLENGE:-}"
    DSM_TLS_DNS_AUTH_HOOK="${DSM_TLS_DNS_AUTH_HOOK:-}"; DSM_TLS_DNS_CLEANUP_HOOK="${DSM_TLS_DNS_CLEANUP_HOOK:-}"
    DSM_TLS_CERT_FILE="${DSM_TLS_CERT_FILE:-}"; DSM_TLS_KEY_FILE="${DSM_TLS_KEY_FILE:-}"; DSM_TLS_CA_FILE="${DSM_TLS_CA_FILE:-}"
    DSM_TLS_LE_EMAIL="${DSM_TLS_LE_EMAIL:-}"; DSM_TLS_SOURCE_CERT_FILE=""; DSM_TLS_SOURCE_KEY_FILE=""

    if [[ -z "${DSM_WEB_SCHEME}" ]]; then
        if web_transport_is_interactive; then
            printf '\n==============================================================\n Transporte do Controller / Dashboard\n==============================================================\n'
            printf 'Escolha como o Dashboard e a API do Controller serão publicados.\n\n'
            printf '  1) HTTP  - permitido para servidor local/LAN confiável\n  2) HTTPS - recomendado para qualquer acesso externo\n\n'
            local answer; read -r -p 'Transporte [1]: ' answer
            case "${answer:-1}" in 1|http|HTTP) DSM_WEB_SCHEME=http ;; 2|https|HTTPS) DSM_WEB_SCHEME=https ;; *) web_transport_die "Transporte inválido: ${answer}" || return 1 ;; esac
        else DSM_WEB_SCHEME=http; fi
    fi
    DSM_WEB_SCHEME="${DSM_WEB_SCHEME,,}"; case "${DSM_WEB_SCHEME}" in http|https) ;; *) web_transport_die "DSM_WEB_SCHEME deve ser http ou https" || return 1;; esac

    if [[ "${DSM_WEB_SCHEME}" == http ]]; then
        DSM_WEB_PORT="${DSM_WEB_PORT:-8080}"; web_transport_validate_port "${DSM_WEB_PORT}" || { web_transport_die "DSM_WEB_PORT inválida: ${DSM_WEB_PORT}" || return 1; }
        DSM_PUBLIC_PORT="${DSM_PUBLIC_PORT:-${DSM_WEB_PORT}}"; web_transport_validate_port "${DSM_PUBLIC_PORT}" || { web_transport_die "DSM_PUBLIC_PORT inválida: ${DSM_PUBLIC_PORT}" || return 1; }
        if web_transport_is_interactive; then printf '\n[AVISO] HTTP não cifra login, cookies ou tráfego do Agent.\nUse esta opção somente em rede local/confiável. Para Internet, escolha HTTPS.\n'; fi
        DSM_TLS_CERT_MODE=disabled; DSM_TLS_ACME_CHALLENGE=disabled; DSM_TLS_CERT_FILE=""; DSM_TLS_KEY_FILE=""; DSM_TLS_CA_FILE=""
    else
        DSM_WEB_PORT="${DSM_WEB_PORT:-8443}"
        if web_transport_is_interactive && [[ -z "${DSM_WEB_PORT_EXPLICIT:-}" ]]; then
            local value
            read -r -p "Porta HTTPS interna [${DSM_WEB_PORT}]: " value
            DSM_WEB_PORT="${value:-${DSM_WEB_PORT}}"
        fi
        web_transport_validate_port "${DSM_WEB_PORT}" || { web_transport_die "DSM_WEB_PORT inválida: ${DSM_WEB_PORT}" || return 1; }

        DSM_PUBLIC_PORT="${DSM_PUBLIC_PORT:-${DSM_WEB_PORT}}"
        if web_transport_is_interactive; then
            local public_port_value
            read -r -p "Porta HTTPS pública [${DSM_PUBLIC_PORT}]: " public_port_value
            DSM_PUBLIC_PORT="${public_port_value:-${DSM_PUBLIC_PORT}}"
        fi
        web_transport_validate_port "${DSM_PUBLIC_PORT}" || { web_transport_die "DSM_PUBLIC_PORT inválida: ${DSM_PUBLIC_PORT}" || return 1; }

        if [[ -z "${DSM_TLS_CERT_MODE}" ]]; then
            if web_transport_is_interactive; then
                printf '\nCertificado HTTPS:\n  1) Let\x27s Encrypt / ACME\n  2) Certificado existente (PEM)\n  3) Certificado local autogerado (LAN/teste; CA privada)\n\n'
                local cert_answer; read -r -p 'Certificado [1]: ' cert_answer
                case "${cert_answer:-1}" in 1|letsencrypt|le|acme) DSM_TLS_CERT_MODE=letsencrypt ;; 2|existing|pem) DSM_TLS_CERT_MODE=existing ;; 3|selfsigned|local) DSM_TLS_CERT_MODE=selfsigned ;; *) web_transport_die "Modo de certificado inválido: ${cert_answer}" || return 1 ;; esac
            else DSM_TLS_CERT_MODE=existing; fi
        fi
        DSM_TLS_CERT_MODE="${DSM_TLS_CERT_MODE,,}"; case "${DSM_TLS_CERT_MODE}" in letsencrypt|existing|selfsigned) ;; *) web_transport_die "DSM_TLS_CERT_MODE inválido" || return 1;; esac

        if [[ "${DSM_TLS_CERT_MODE}" == letsencrypt ]]; then
            if web_transport_is_interactive; then
                local value; read -r -p "Hostname público [${DSM_PUBLIC_HOST:-controller.example.com}]: " value; DSM_PUBLIC_HOST="${value:-${DSM_PUBLIC_HOST}}"
                read -r -p "E-mail Let's Encrypt [${DSM_TLS_LE_EMAIL:-}]: " value; DSM_TLS_LE_EMAIL="${value:-${DSM_TLS_LE_EMAIL}}"
            fi
            [[ -n "${DSM_PUBLIC_HOST}" ]] || { web_transport_die "DSM_PUBLIC_HOST é obrigatório para Let's Encrypt" || return 1; }
            [[ "${DSM_PUBLIC_HOST}" != *' '* && "${DSM_PUBLIC_HOST}" == *.* ]] || { web_transport_die "Hostname público inválido: ${DSM_PUBLIC_HOST}" || return 1; }
            [[ -n "${DSM_TLS_LE_EMAIL}" ]] || { web_transport_die "DSM_TLS_LE_EMAIL é obrigatório para Let's Encrypt" || return 1; }
            web_transport_select_acme_challenge || return 1
            DSM_TLS_SOURCE_CERT_FILE="/etc/letsencrypt/live/${DSM_PUBLIC_HOST}/fullchain.pem"; DSM_TLS_SOURCE_KEY_FILE="/etc/letsencrypt/live/${DSM_PUBLIC_HOST}/privkey.pem"
            DSM_TLS_CERT_FILE="/etc/capivara/tls/server.crt"; DSM_TLS_KEY_FILE="/etc/capivara/tls/server.key"; DSM_TLS_CA_FILE=""
        elif [[ "${DSM_TLS_CERT_MODE}" == existing ]]; then
            DSM_TLS_ACME_CHALLENGE=disabled
            if web_transport_is_interactive; then
                local value; read -r -p "Hostname público [${DSM_PUBLIC_HOST:-}]: " value; DSM_PUBLIC_HOST="${value:-${DSM_PUBLIC_HOST}}"
                read -r -p "Certificado PEM [${DSM_TLS_CERT_FILE:-/etc/capivara/tls/server.crt}]: " value; DSM_TLS_CERT_FILE="${value:-${DSM_TLS_CERT_FILE:-/etc/capivara/tls/server.crt}}"
                read -r -p "Chave privada PEM [${DSM_TLS_KEY_FILE:-/etc/capivara/tls/server.key}]: " value; DSM_TLS_KEY_FILE="${value:-${DSM_TLS_KEY_FILE:-/etc/capivara/tls/server.key}}"
                read -r -p "CA privada para Agents (opcional) [${DSM_TLS_CA_FILE:-}]: " value; DSM_TLS_CA_FILE="${value:-${DSM_TLS_CA_FILE}}"
            fi
            [[ -n "${DSM_TLS_CERT_FILE}" && -n "${DSM_TLS_KEY_FILE}" ]] || { web_transport_die "Certificado e chave são obrigatórios em HTTPS existing" || return 1; }
        else
            DSM_TLS_ACME_CHALLENGE=disabled
            if web_transport_is_interactive; then local value; read -r -p "Nome DNS/IP do Controller [${DSM_PUBLIC_HOST:-$(hostname -f 2>/dev/null || hostname)}]: " value; DSM_PUBLIC_HOST="${value:-${DSM_PUBLIC_HOST:-$(hostname -f 2>/dev/null || hostname)}}"; fi
            DSM_PUBLIC_HOST="${DSM_PUBLIC_HOST:-localhost}"; DSM_TLS_CERT_FILE="${DSM_TLS_CERT_FILE:-/etc/capivara/tls/server.crt}"; DSM_TLS_KEY_FILE="${DSM_TLS_KEY_FILE:-/etc/capivara/tls/server.key}"; DSM_TLS_CA_FILE="${DSM_TLS_CA_FILE:-/etc/capivara/tls/server.crt}"
        fi
    fi

    if [[ -n "${DSM_PUBLIC_HOST}" ]]; then DSM_CONTROLLER_PUBLIC_URL="$(web_transport_public_url)"; else DSM_CONTROLLER_PUBLIC_URL=""; fi
    export DSM_WEB_SCHEME DSM_WEB_HOST DSM_WEB_PORT DSM_PUBLIC_HOST DSM_PUBLIC_PORT DSM_CONTROLLER_PUBLIC_URL
    export DSM_TLS_CERT_MODE DSM_TLS_ACME_CHALLENGE DSM_TLS_DNS_AUTH_HOOK DSM_TLS_DNS_CLEANUP_HOOK
    export DSM_TLS_CERT_FILE DSM_TLS_KEY_FILE DSM_TLS_CA_FILE DSM_TLS_LE_EMAIL DSM_TLS_SOURCE_CERT_FILE DSM_TLS_SOURCE_KEY_FILE
}

prepare_web_transport_certificate(){
    [[ "${DSM_WEB_SCHEME:-http}" == https ]] || return 0; [[ " ${*} " != *" --dry-run "* ]] || return 0
    if [[ "${DSM_TLS_CERT_MODE}" == existing ]]; then
        [[ -r "${DSM_TLS_CERT_FILE}" ]] || { web_transport_die "Certificado não encontrado: ${DSM_TLS_CERT_FILE}" || return 1; }; [[ -r "${DSM_TLS_KEY_FILE}" ]] || { web_transport_die "Chave privada não encontrada: ${DSM_TLS_KEY_FILE}" || return 1; }
        [[ -z "${DSM_TLS_CA_FILE}" || -r "${DSM_TLS_CA_FILE}" ]] || { web_transport_die "CA privada não encontrada: ${DSM_TLS_CA_FILE}" || return 1; }; return 0
    fi
    if [[ "${DSM_TLS_CERT_MODE}" == selfsigned ]]; then
        command -v openssl >/dev/null 2>&1 || { web_transport_die "openssl é necessário para certificado local" || return 1; }; install -d -m 700 -o root -g root "$(dirname "${DSM_TLS_KEY_FILE}")"
        local san; if [[ "${DSM_PUBLIC_HOST}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then san="IP:${DSM_PUBLIC_HOST}"; else san="DNS:${DSM_PUBLIC_HOST}"; fi
        openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 -subj "/CN=${DSM_PUBLIC_HOST}" -addext "subjectAltName=${san}" -keyout "${DSM_TLS_KEY_FILE}" -out "${DSM_TLS_CERT_FILE}" >/dev/null 2>&1
        chmod 600 "${DSM_TLS_KEY_FILE}"; chmod 644 "${DSM_TLS_CERT_FILE}"; printf '[Capivara] CA/certificado local para Agents: %s\n' "${DSM_TLS_CA_FILE}"; return 0
    fi
    command -v certbot >/dev/null 2>&1 || { if command -v apt-get >/dev/null 2>&1; then DEBIAN_FRONTEND=noninteractive apt-get update >/dev/null; DEBIAN_FRONTEND=noninteractive apt-get install -y certbot >/dev/null; fi; }
    command -v certbot >/dev/null 2>&1 || { web_transport_die "certbot não está disponível" || return 1; }

    case "${DSM_TLS_ACME_CHALLENGE:-http-01}" in
        http-01)
            printf '[Capivara] ACME HTTP-01 requer a porta pública TCP/80 acessível durante emissão e renovação.\n'
            certbot certonly --standalone --non-interactive --agree-tos --email "${DSM_TLS_LE_EMAIL}" -d "${DSM_PUBLIC_HOST}"
            ;;
        dns-01-manual)
            web_transport_is_interactive || { web_transport_die "DNS-01 manual requer instalação interativa; use dns-01-hook em automação" || return 1; }
            printf '[Capivara] O Certbot solicitará um registro TXT em _acme-challenge.%s.\n' "${DSM_PUBLIC_HOST}"
            certbot certonly --manual --preferred-challenges dns --agree-tos --email "${DSM_TLS_LE_EMAIL}" -d "${DSM_PUBLIC_HOST}"
            ;;
        dns-01-hook)
            certbot certonly --manual --preferred-challenges dns --non-interactive --agree-tos --email "${DSM_TLS_LE_EMAIL}" \
                --manual-auth-hook "${DSM_TLS_DNS_AUTH_HOOK}" --manual-cleanup-hook "${DSM_TLS_DNS_CLEANUP_HOOK}" -d "${DSM_PUBLIC_HOST}"
            ;;
        *) web_transport_die "Desafio ACME não suportado: ${DSM_TLS_ACME_CHALLENGE}" || return 1 ;;
    esac
    [[ -r "${DSM_TLS_SOURCE_CERT_FILE}" && -r "${DSM_TLS_SOURCE_KEY_FILE}" ]] || { web_transport_die "Let's Encrypt não produziu o certificado esperado" || return 1; }
}

persist_web_transport_config(){
    [[ "${DSM_NODE_ROLE:-}" == controller || "${DSM_NODE_ROLE:-}" == hybrid ]] || return 0; [[ " ${*} " != *" --dry-run "* ]] || return 0
    local config="${DSM_ROOT:-/opt/dsm}/config/dsm.conf" group="${DSM_SERVICE_GROUP:-$(id -gn)}" user="${DSM_SERVICE_USER:-$(id -un)}"
    [[ -f "${config}" ]] || { web_transport_die "Configuração instalada não encontrada: ${config}" || return 1; }

    if [[ "${DSM_WEB_SCHEME}" == https ]]; then
        if [[ "${DSM_TLS_CERT_MODE}" == letsencrypt ]]; then
            install -d -m 750 -o root -g "${group}" /etc/capivara/tls
            install -m 0644 -o root -g "${group}" "${DSM_TLS_SOURCE_CERT_FILE}" "${DSM_TLS_CERT_FILE}"
            install -m 0640 -o root -g "${group}" "${DSM_TLS_SOURCE_KEY_FILE}" "${DSM_TLS_KEY_FILE}"
            install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
            cat >/etc/letsencrypt/renewal-hooks/deploy/capivara-dashboard <<EOF_HOOK
#!/bin/sh
set -e
install -m 0644 -o root -g '${group}' '${DSM_TLS_SOURCE_CERT_FILE}' '${DSM_TLS_CERT_FILE}'
install -m 0640 -o root -g '${group}' '${DSM_TLS_SOURCE_KEY_FILE}' '${DSM_TLS_KEY_FILE}'
systemctl try-restart dsm-dashboard.service >/dev/null 2>&1 || true
EOF_HOOK
            chmod 755 /etc/letsencrypt/renewal-hooks/deploy/capivara-dashboard
        elif [[ "${DSM_TLS_CERT_MODE}" == selfsigned ]]; then
            chown root:"${group}" "${DSM_TLS_CERT_FILE}" "${DSM_TLS_KEY_FILE}"; chmod 0644 "${DSM_TLS_CERT_FILE}"; chmod 0640 "${DSM_TLS_KEY_FILE}"
        else
            runuser -u "${user}" -- test -r "${DSM_TLS_CERT_FILE}" || { web_transport_die "Usuário ${user} não consegue ler o certificado existente" || return 1; }
            runuser -u "${user}" -- test -r "${DSM_TLS_KEY_FILE}" || { web_transport_die "Usuário ${user} não consegue ler a chave existente; ajuste owner/grupo sem torná-la pública" || return 1; }
        fi
    fi

    web_transport_write_config_value "${config}" DSM_WEB_SCHEME "${DSM_WEB_SCHEME}"; web_transport_write_config_value "${config}" DSM_WEB_HOST "${DSM_WEB_HOST}"; web_transport_write_config_value "${config}" DSM_WEB_PORT "${DSM_WEB_PORT}"
    web_transport_write_config_value "${config}" DSM_PUBLIC_HOST "${DSM_PUBLIC_HOST:-}"; web_transport_write_config_value "${config}" DSM_PUBLIC_PORT "${DSM_PUBLIC_PORT:-${DSM_WEB_PORT}}"; web_transport_write_config_value "${config}" DSM_CONTROLLER_PUBLIC_URL "${DSM_CONTROLLER_PUBLIC_URL:-}"
    web_transport_write_config_value "${config}" DSM_TLS_CERT_MODE "${DSM_TLS_CERT_MODE:-disabled}"; web_transport_write_config_value "${config}" DSM_TLS_ACME_CHALLENGE "${DSM_TLS_ACME_CHALLENGE:-disabled}"
    web_transport_write_config_value "${config}" DSM_TLS_DNS_AUTH_HOOK "${DSM_TLS_DNS_AUTH_HOOK:-}"; web_transport_write_config_value "${config}" DSM_TLS_DNS_CLEANUP_HOOK "${DSM_TLS_DNS_CLEANUP_HOOK:-}"
    web_transport_write_config_value "${config}" DSM_TLS_CERT_FILE "${DSM_TLS_CERT_FILE:-}"; web_transport_write_config_value "${config}" DSM_TLS_KEY_FILE "${DSM_TLS_KEY_FILE:-}"; web_transport_write_config_value "${config}" DSM_TLS_CA_FILE "${DSM_TLS_CA_FILE:-}"
    if command -v systemctl >/dev/null 2>&1 && systemctl cat dsm-dashboard.service >/dev/null 2>&1; then systemctl restart dsm-dashboard.service; systemctl is-active --quiet dsm-dashboard.service || { web_transport_die "Dashboard não iniciou após aplicar ${DSM_WEB_SCHEME^^}" || return 1; }; fi
}
