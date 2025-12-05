#!/bin/bash
#
# Ceph Management REST API - Deployment Validation Script
# This script validates the installation and configuration
#
# Usage: sudo ./validate.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/ceph-api"
DATA_DIR="/opt/ceph-api/data"
CONFIG_DIR="/opt/ceph-api/config"
SERVICE_NAME="ceph-api"
API_PORT=8080
API_HOST="10.10.2.20"

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
WARNING_TESTS=0

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

test_pass() {
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    PASSED_TESTS=$((PASSED_TESTS + 1))
    log_success "$1"
}

test_fail() {
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    FAILED_TESTS=$((FAILED_TESTS + 1))
    log_error "$1"
}

test_warn() {
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    WARNING_TESTS=$((WARNING_TESTS + 1))
    log_warning "$1"
}

show_help() {
    cat << EOF
Ceph Management REST API - Deployment Validation Script

Usage: $0 [OPTIONS]

Options:
    -h, --help              Show this help message
    --skip-api-test         Skip API connectivity tests
    --skip-ceph-test        Skip Ceph connectivity tests
    --api-key KEY           API key for testing authenticated endpoints

Examples:
    $0
    $0 --api-key your-api-key-here
    $0 --skip-ceph-test

EOF
    exit 0
}

print_header() {
    echo ""
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}  Ceph API Deployment Validation${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo ""
}

print_section() {
    echo ""
    echo -e "${BLUE}--- $1 ---${NC}"
}

# Validation Tests

validate_user() {
    print_section "User and Permissions"

    if id ceph-api &>/dev/null; then
        test_pass "User 'ceph-api' exists"
    else
        test_fail "User 'ceph-api' does not exist"
        return
    fi

    if groups ceph-api | grep -q ceph; then
        test_pass "User 'ceph-api' is in 'ceph' group"
    else
        test_warn "User 'ceph-api' is not in 'ceph' group (may not have Ceph access)"
    fi
}

validate_directories() {
    print_section "Directory Structure"

    if [[ -d "$INSTALL_DIR" ]]; then
        test_pass "Installation directory exists: $INSTALL_DIR"
    else
        test_fail "Installation directory missing: $INSTALL_DIR"
        return
    fi

    if [[ -d "$INSTALL_DIR/app" ]]; then
        test_pass "Application directory exists"
    else
        test_fail "Application directory missing"
    fi

    if [[ -d "$INSTALL_DIR/venv" ]]; then
        test_pass "Virtual environment exists"
    else
        test_fail "Virtual environment missing"
    fi

    if [[ -d "$DATA_DIR" ]]; then
        test_pass "Data directory exists"
    else
        test_fail "Data directory missing"
    fi

    if [[ -d "$CONFIG_DIR" ]]; then
        test_pass "Config directory exists"
    else
        test_fail "Config directory missing"
    fi

    # Check ownership
    if [[ $(stat -f '%Su' "$INSTALL_DIR" 2>/dev/null || stat -c '%U' "$INSTALL_DIR" 2>/dev/null) == "ceph-api" ]]; then
        test_pass "Installation directory owned by ceph-api"
    else
        test_fail "Installation directory not owned by ceph-api"
    fi
}

validate_files() {
    print_section "Required Files"

    if [[ -f "$INSTALL_DIR/app/main.py" ]]; then
        test_pass "Main application file exists"
    else
        test_fail "Main application file missing"
    fi

    if [[ -f "$CONFIG_DIR/config.yaml" ]]; then
        test_pass "Configuration file exists"
    else
        test_warn "Configuration file missing (may use defaults)"
    fi

    if [[ -f "$INSTALL_DIR/requirements.txt" ]]; then
        test_pass "Requirements file exists"
    else
        test_warn "Requirements file missing"
    fi
}

validate_databases() {
    print_section "Databases"

    if [[ -f "$DATA_DIR/api_keys.db" ]]; then
        test_pass "API keys database exists"

        # Check if database is readable
        if sudo -u ceph-api sqlite3 "$DATA_DIR/api_keys.db" "SELECT COUNT(*) FROM sqlite_master;" &>/dev/null; then
            test_pass "API keys database is readable"
        else
            test_fail "API keys database is not readable"
        fi
    else
        test_fail "API keys database missing"
    fi

    if [[ -f "$DATA_DIR/audit.db" ]]; then
        test_pass "Audit database exists"
    else
        test_warn "Audit database missing (audit logging may not work)"
    fi
}

validate_python_env() {
    print_section "Python Environment"

    if [[ -x "$INSTALL_DIR/venv/bin/python" ]]; then
        test_pass "Python executable exists in venv"

        PYTHON_VERSION=$("$INSTALL_DIR/venv/bin/python" --version 2>&1)
        log_info "Python version: $PYTHON_VERSION"
    else
        test_fail "Python executable missing in venv"
        return
    fi

    # Check key dependencies
    if sudo -u ceph-api "$INSTALL_DIR/venv/bin/python" -c "import fastapi" 2>/dev/null; then
        test_pass "FastAPI is installed"
    else
        test_fail "FastAPI is not installed"
    fi

    if sudo -u ceph-api "$INSTALL_DIR/venv/bin/python" -c "import uvicorn" 2>/dev/null; then
        test_pass "Uvicorn is installed"
    else
        test_fail "Uvicorn is not installed"
    fi

    if sudo -u ceph-api "$INSTALL_DIR/venv/bin/python" -c "import rados" 2>/dev/null; then
        test_pass "Python Ceph library (rados) is available"
    else
        test_fail "Python Ceph library (rados) is not available"
    fi
}

validate_systemd() {
    print_section "Systemd Service"

    if [[ -f "/etc/systemd/system/$SERVICE_NAME.service" ]]; then
        test_pass "Systemd service file exists"
    else
        test_fail "Systemd service file missing"
        return
    fi

    if systemctl is-enabled --quiet "$SERVICE_NAME.service" 2>/dev/null; then
        test_pass "Service is enabled"
    else
        test_warn "Service is not enabled (will not start on boot)"
    fi

    if systemctl is-active --quiet "$SERVICE_NAME.service"; then
        test_pass "Service is running"
    else
        test_fail "Service is not running"
    fi

    # Check for recent failures
    if journalctl -u "$SERVICE_NAME.service" --since "1 hour ago" -p err --quiet; then
        test_warn "Recent errors found in service logs"
    else
        test_pass "No recent errors in service logs"
    fi
}

validate_network() {
    print_section "Network Configuration"

    # Check if port is listening
    if ss -tlnp 2>/dev/null | grep -q ":$API_PORT "; then
        test_pass "Port $API_PORT is listening"

        # Check which process is listening
        LISTENING_PROCESS=$(ss -tlnp 2>/dev/null | grep ":$API_PORT " | awk '{print $NF}' | head -1)
        log_info "Listening process: $LISTENING_PROCESS"
    else
        test_fail "Port $API_PORT is not listening"
    fi

    # Check firewall
    if command -v ufw &> /dev/null; then
        if ufw status 2>/dev/null | grep -q "$API_PORT"; then
            test_pass "UFW rules exist for port $API_PORT"
        else
            test_warn "No UFW rules found for port $API_PORT"
        fi
    elif command -v iptables &> /dev/null; then
        if iptables -L INPUT -n | grep -q "dpt:$API_PORT"; then
            test_pass "iptables rules exist for port $API_PORT"
        else
            test_warn "No iptables rules found for port $API_PORT"
        fi
    else
        test_warn "No firewall detected"
    fi
}

validate_api() {
    if [[ "$SKIP_API_TEST" == true ]]; then
        print_section "API Tests (Skipped)"
        return
    fi

    print_section "API Connectivity"

    # Check health endpoint
    if curl -f -s -m 5 "http://${API_HOST}:${API_PORT}/health" &>/dev/null; then
        test_pass "Health endpoint is accessible"
    else
        test_fail "Health endpoint is not accessible"
    fi

    # Check API documentation
    if curl -f -s -m 5 "http://${API_HOST}:${API_PORT}/docs" &>/dev/null; then
        test_pass "API documentation is accessible"
    else
        test_warn "API documentation is not accessible"
    fi

    # Test authenticated endpoint if API key provided
    if [[ -n "$API_KEY" ]]; then
        if curl -f -s -m 5 -H "X-API-Key: $API_KEY" "http://${API_HOST}:${API_PORT}/api/v1/fs/list" &>/dev/null; then
            test_pass "Authenticated API endpoint is accessible"
        else
            test_fail "Authenticated API endpoint is not accessible (check API key)"
        fi
    else
        test_warn "API key not provided, skipping authenticated endpoint test"
    fi
}

validate_ceph() {
    if [[ "$SKIP_CEPH_TEST" == true ]]; then
        print_section "Ceph Connectivity (Skipped)"
        return
    fi

    print_section "Ceph Connectivity"

    # Check Ceph config
    if [[ -f /etc/ceph/ceph.conf ]]; then
        test_pass "Ceph configuration file exists"
    else
        test_fail "Ceph configuration file missing"
        return
    fi

    if [[ -f /etc/ceph/ceph.client.admin.keyring ]]; then
        test_pass "Ceph admin keyring exists"
    else
        test_fail "Ceph admin keyring missing"
        return
    fi

    # Test Ceph connectivity as ceph-api user
    if sudo -u ceph-api ceph -s &>/dev/null; then
        test_pass "Can connect to Ceph cluster as ceph-api user"
    else
        test_fail "Cannot connect to Ceph cluster as ceph-api user"
    fi

    # Check Ceph cluster health
    CEPH_HEALTH=$(sudo -u ceph-api ceph health 2>/dev/null | awk '{print $1}')
    if [[ "$CEPH_HEALTH" == "HEALTH_OK" ]]; then
        test_pass "Ceph cluster health is OK"
    elif [[ "$CEPH_HEALTH" == "HEALTH_WARN" ]]; then
        test_warn "Ceph cluster health is WARN"
    else
        test_warn "Ceph cluster health is $CEPH_HEALTH"
    fi
}

validate_security() {
    print_section "Security Configuration"

    # Check file permissions
    INSTALL_DIR_PERMS=$(stat -f '%Lp' "$INSTALL_DIR" 2>/dev/null || stat -c '%a' "$INSTALL_DIR" 2>/dev/null)
    if [[ "$INSTALL_DIR_PERMS" == "750" ]] || [[ "$INSTALL_DIR_PERMS" == "755" ]]; then
        test_pass "Installation directory has secure permissions"
    else
        test_warn "Installation directory permissions are $INSTALL_DIR_PERMS (should be 750)"
    fi

    # Check if config file is readable by ceph-api user
    if sudo -u ceph-api test -r "$CONFIG_DIR/config.yaml" 2>/dev/null; then
        test_pass "Config file is readable by ceph-api user"
    else
        test_warn "Config file is not readable by ceph-api user"
    fi

    # Check if running as root
    SERVICE_USER=$(systemctl show "$SERVICE_NAME.service" -p User --value 2>/dev/null)
    if [[ "$SERVICE_USER" == "ceph-api" ]]; then
        test_pass "Service is running as non-root user"
    else
        test_fail "Service is not running as ceph-api user"
    fi

    # Check for admin API key file
    if [[ -f /root/.ceph-api-admin-key ]]; then
        test_pass "Admin API key file exists"

        KEY_PERMS=$(stat -f '%Lp' /root/.ceph-api-admin-key 2>/dev/null || stat -c '%a' /root/.ceph-api-admin-key 2>/dev/null)
        if [[ "$KEY_PERMS" == "600" ]]; then
            test_pass "Admin API key file has secure permissions"
        else
            test_warn "Admin API key file permissions are $KEY_PERMS (should be 600)"
        fi
    else
        test_warn "Admin API key file not found at /root/.ceph-api-admin-key"
    fi
}

validate_resources() {
    print_section "Resource Usage"

    # Check memory usage
    if systemctl show "$SERVICE_NAME.service" -p MemoryCurrent --value &>/dev/null; then
        MEMORY_BYTES=$(systemctl show "$SERVICE_NAME.service" -p MemoryCurrent --value)
        MEMORY_MB=$((MEMORY_BYTES / 1024 / 1024))

        if [[ $MEMORY_MB -lt 1024 ]]; then
            test_pass "Memory usage is ${MEMORY_MB}MB (within limits)"
        else
            test_warn "Memory usage is ${MEMORY_MB}MB (may need adjustment)"
        fi
    else
        test_warn "Cannot determine memory usage"
    fi

    # Check if service has restarted recently
    RESTART_COUNT=$(systemctl show "$SERVICE_NAME.service" -p NRestarts --value 2>/dev/null || echo "0")
    if [[ $RESTART_COUNT -eq 0 ]]; then
        test_pass "Service has not restarted unexpectedly"
    else
        test_warn "Service has restarted $RESTART_COUNT time(s)"
    fi
}

validate_logs() {
    print_section "Logging"

    # Check if logs are being written
    if journalctl -u "$SERVICE_NAME.service" -n 1 --quiet; then
        test_pass "Service logs are available in journald"
    else
        test_warn "No service logs found in journald"
    fi

    # Check for common error patterns
    ERROR_COUNT=$(journalctl -u "$SERVICE_NAME.service" --since "1 hour ago" -p err --no-pager | wc -l)
    if [[ $ERROR_COUNT -eq 0 ]]; then
        test_pass "No errors in last hour"
    else
        test_warn "$ERROR_COUNT error(s) in last hour"
    fi
}

print_summary() {
    echo ""
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}  Validation Summary${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo ""
    echo "Total tests:    $TOTAL_TESTS"
    echo -e "${GREEN}Passed:         $PASSED_TESTS${NC}"
    echo -e "${YELLOW}Warnings:       $WARNING_TESTS${NC}"
    echo -e "${RED}Failed:         $FAILED_TESTS${NC}"
    echo ""

    if [[ $FAILED_TESTS -eq 0 ]]; then
        if [[ $WARNING_TESTS -eq 0 ]]; then
            echo -e "${GREEN}✓ Deployment is healthy!${NC}"
        else
            echo -e "${YELLOW}⚠ Deployment is functional but has warnings${NC}"
        fi
    else
        echo -e "${RED}✗ Deployment has issues that need attention${NC}"
    fi

    echo ""
}

# Main validation flow
main() {
    SKIP_API_TEST=false
    SKIP_CEPH_TEST=false
    API_KEY=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                ;;
            --skip-api-test)
                SKIP_API_TEST=true
                shift
                ;;
            --skip-ceph-test)
                SKIP_CEPH_TEST=true
                shift
                ;;
            --api-key)
                API_KEY="$2"
                shift 2
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                ;;
        esac
    done

    print_header

    validate_user
    validate_directories
    validate_files
    validate_databases
    validate_python_env
    validate_systemd
    validate_network
    validate_api
    validate_ceph
    validate_security
    validate_resources
    validate_logs

    print_summary

    # Exit with appropriate code
    if [[ $FAILED_TESTS -gt 0 ]]; then
        exit 1
    elif [[ $WARNING_TESTS -gt 0 ]]; then
        exit 0
    else
        exit 0
    fi
}

# Run main function
main "$@"
