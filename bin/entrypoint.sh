#!/bin/bash
set -e

APP_HOME="${APP_HOME:-/opt/registry-center}"
cd "$APP_HOME"

export PATH="/opt/venv/bin:$PATH"

# ─────────────────────────────────────────────────────────────────────
# Cloud Run environment variable → config file override
# The application reads from config files, not env vars.
# This bridge writes env var values into the config files so they
# take effect at runtime.
# ─────────────────────────────────────────────────────────────────────

SERVER_CONF="etc/conf/server.conf"
PERSISTENCE_CONF="etc/conf/persistence.conf"

# Escape sed metacharacters (&, backslash, delimiter #) in override values so
# credentials or hosts containing them don't corrupt the config file.
sed_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/[&#]/\\&/g'
}

# --- server.conf overrides (using # as sed delimiter to handle paths safely) ---
if [ -n "${REGISTRY_IP}" ]; then
    sed -i "s#^IP=.*#IP=${REGISTRY_IP}#" "${SERVER_CONF}"
    echo "Config override: IP=${REGISTRY_IP}"
fi

# Cloud Run injects PORT env var
if [ -n "${PORT}" ]; then
    sed -i "s#^PORT=.*#PORT=${PORT}#" "${SERVER_CONF}"
    echo "Config override: PORT=${PORT} (Cloud Run)"
elif [ -n "${REGISTRY_PORT}" ]; then
    sed -i "s#^PORT=.*#PORT=${REGISTRY_PORT}#" "${SERVER_CONF}"
    echo "Config override: PORT=${REGISTRY_PORT}"
fi

if [ -n "${REGISTRY_ENABLE_HTTPS}" ]; then
    sed -i "s#^enable_https=.*#enable_https=${REGISTRY_ENABLE_HTTPS}#" "${SERVER_CONF}"
    echo "Config override: enable_https=${REGISTRY_ENABLE_HTTPS}"
fi

if [ -n "${REGISTRY_FORWARDED_ALLOW_IPS}" ]; then
    sed -i "s#^forwarded_allow_ips=.*#forwarded_allow_ips=\"${REGISTRY_FORWARDED_ALLOW_IPS}\"#" "${SERVER_CONF}"
    echo "Config override: forwarded_allow_ips=${REGISTRY_FORWARDED_ALLOW_IPS}"
fi

if [ -n "${REGISTRY_OWNER__VALIDATION__MODE}" ]; then
    sed -i "s#^owner.validation.mode=.*#owner.validation.mode=${REGISTRY_OWNER__VALIDATION__MODE}#" "${SERVER_CONF}"
    echo "Config override: owner.validation.mode=${REGISTRY_OWNER__VALIDATION__MODE}"
fi

# When HTTPS is disabled, also disable cert verification and registry signing
if [ "${REGISTRY_ENABLE_HTTPS}" = "false" ]; then
    sed -i "s#^verify_client=.*#verify_client=false#" "${SERVER_CONF}"
    sed -i "s#^registry.sign.enabled=.*#registry.sign.enabled=false#" "${SERVER_CONF}"
    sed -i "s#^signature_validation_enabled=.*#signature_validation_enabled=false#" "${SERVER_CONF}"
    sed -i "s#^owner.isolation.enabled=.*#owner.isolation.enabled=false#" "${SERVER_CONF}"
    echo "Config override: HTTPS disabled → verify_client=false, signing/validation disabled"
fi

# --- persistence.conf overrides (using # to handle /cloudsql/ paths safely) ---
if [ -n "${PERSISTENCE_MODE}" ]; then
    sed -i "s#^persistence.mode=.*#persistence.mode=${PERSISTENCE_MODE}#" "${PERSISTENCE_CONF}"
    echo "Config override: persistence.mode=${PERSISTENCE_MODE}"
fi

if [ -n "${DB_HOST}" ]; then
    sed -i "s#^postgresql.host=.*#postgresql.host=$(sed_escape "${DB_HOST}")#" "${PERSISTENCE_CONF}"
    echo "Config override: postgresql.host=${DB_HOST}"
fi

if [ -n "${DB_PORT}" ]; then
    sed -i "s#^postgresql.port=.*#postgresql.port=$(sed_escape "${DB_PORT}")#" "${PERSISTENCE_CONF}"
    echo "Config override: postgresql.port=${DB_PORT}"
fi

if [ -n "${DB_NAME}" ]; then
    sed -i "s#^postgresql.name=.*#postgresql.name=$(sed_escape "${DB_NAME}")#" "${PERSISTENCE_CONF}"
    echo "Config override: postgresql.name=${DB_NAME}"
fi

if [ -n "${DB_USERNAME}" ]; then
    sed -i "s#^postgresql.username=.*#postgresql.username=$(sed_escape "${DB_USERNAME}")#" "${PERSISTENCE_CONF}"
    echo "Config override: postgresql.username=${DB_USERNAME}"
fi

if [ -n "${DB_PASSWORD}" ]; then
    sed -i "s#^postgresql.password=.*#postgresql.password=$(sed_escape "${DB_PASSWORD}")#" "${PERSISTENCE_CONF}"
    echo "Config override: postgresql.password=***"
fi

if [ -n "${DB_POOL_MIN}" ]; then
    sed -i "s#^postgresql.pool.min=.*#postgresql.pool.min=$(sed_escape "${DB_POOL_MIN}")#" "${PERSISTENCE_CONF}"
    echo "Config override: postgresql.pool.min=${DB_POOL_MIN}"
fi

if [ -n "${DB_POOL_MAX}" ]; then
    sed -i "s#^postgresql.pool.max=.*#postgresql.pool.max=$(sed_escape "${DB_POOL_MAX}")#" "${PERSISTENCE_CONF}"
    echo "Config override: postgresql.pool.max=${DB_POOL_MAX}"
fi

# --- generic DB_* override for gauss / mysql modes (postgresql handled above) ---
# The gauss/mysql blocks in persistence.conf resolve ${GAUSS_*} / ${MYSQL_*}
# env vars natively; DB_* is the container convention shared with the
# postgresql block above.
if [ "${PERSISTENCE_MODE}" = "gauss" ] || [ "${PERSISTENCE_MODE}" = "mysql" ]; then
    _db_prefix="${PERSISTENCE_MODE}"
    _db_name_key="name"
    if [ "${PERSISTENCE_MODE}" = "gauss" ]; then
        _db_name_key="database"
    fi

    if [ -n "${DB_HOST}" ]; then
        sed -i "s#^${_db_prefix}.host=.*#${_db_prefix}.host=$(sed_escape "${DB_HOST}")#" "${PERSISTENCE_CONF}"
        echo "Config override: ${_db_prefix}.host=${DB_HOST}"
    fi

    if [ -n "${DB_PORT}" ]; then
        sed -i "s#^${_db_prefix}.port=.*#${_db_prefix}.port=$(sed_escape "${DB_PORT}")#" "${PERSISTENCE_CONF}"
        echo "Config override: ${_db_prefix}.port=${DB_PORT}"
    fi

    if [ -n "${DB_NAME}" ]; then
        sed -i "s#^${_db_prefix}.${_db_name_key}=.*#${_db_prefix}.${_db_name_key}=$(sed_escape "${DB_NAME}")#" "${PERSISTENCE_CONF}"
        echo "Config override: ${_db_prefix}.${_db_name_key}=${DB_NAME}"
    fi

    if [ -n "${DB_USERNAME}" ]; then
        sed -i "s#^${_db_prefix}.username=.*#${_db_prefix}.username=$(sed_escape "${DB_USERNAME}")#" "${PERSISTENCE_CONF}"
        echo "Config override: ${_db_prefix}.username=${DB_USERNAME}"
    fi

    if [ -n "${DB_PASSWORD}" ]; then
        sed -i "s#^${_db_prefix}.password=.*#${_db_prefix}.password=$(sed_escape "${DB_PASSWORD}")#" "${PERSISTENCE_CONF}"
        echo "Config override: ${_db_prefix}.password=***"
    fi

    if [ -n "${DB_POOL_MIN}" ]; then
        sed -i "s#^${_db_prefix}.pool.min=.*#${_db_prefix}.pool.min=$(sed_escape "${DB_POOL_MIN}")#" "${PERSISTENCE_CONF}"
        echo "Config override: ${_db_prefix}.pool.min=${DB_POOL_MIN}"
    fi

    if [ -n "${DB_POOL_MAX}" ]; then
        sed -i "s#^${_db_prefix}.pool.max=.*#${_db_prefix}.pool.max=$(sed_escape "${DB_POOL_MAX}")#" "${PERSISTENCE_CONF}"
        echo "Config override: ${_db_prefix}.pool.max=${DB_POOL_MAX}"
    fi

    if [ -n "${DB_CONNECT_TIMEOUT}" ]; then
        sed -i "s#^${_db_prefix}.connect_timeout=.*#${_db_prefix}.connect_timeout=$(sed_escape "${DB_CONNECT_TIMEOUT}")#" "${PERSISTENCE_CONF}"
        echo "Config override: ${_db_prefix}.connect_timeout=${DB_CONNECT_TIMEOUT}"
    fi
fi

# Ensure run/ directory exists for internal UDS service
mkdir -p run

if [ "${1}" = "init" ]; then
    shift
    echo "Running registry-center initialization (non-interactive)..."
    exec python -m agent_registry.init --non-interactive "$@"
fi

if [ "${1}" = "serve" ]; then
    echo "Starting registry-center service..."
    exec python -m agent_registry.start
fi

exec "$@"
