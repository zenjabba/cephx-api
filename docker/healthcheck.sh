#!/bin/sh
#
# Docker health check script for Ceph Management REST API
#

set -e

# Configuration
API_HOST="${API_HOST:-localhost}"
API_PORT="${API_PORT:-8080}"
HEALTH_ENDPOINT="${HEALTH_ENDPOINT:-/health}"
TIMEOUT="${TIMEOUT:-5}"

# Perform health check
curl -f -s -m "$TIMEOUT" "http://${API_HOST}:${API_PORT}${HEALTH_ENDPOINT}" >/dev/null || exit 1

exit 0
