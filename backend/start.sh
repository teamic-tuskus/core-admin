#!/usr/bin/env sh
set -eu

# Default checkout bypass to true for local development only.
# Production is still protected by backend environment checks.
if [ "${COREADMIN_ENVIRONMENT:-local}" = "local" ] && [ -z "${COREADMIN_CHECKOUT_TEST_PAYMENT_BYPASS_ENABLED:-}" ]; then
    export COREADMIN_CHECKOUT_TEST_PAYMENT_BYPASS_ENABLED=true
fi

exec python -m uvicorn app.main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8080}" \
    --workers "${WORKERS:-1}"
