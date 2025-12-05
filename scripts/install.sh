#!/bin/bash
#
# Ceph Management REST API - Installation Script
# This script installs the Ceph API service on Ubuntu/Debian systems
#
# Usage: sudo ./install.sh
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
LOG_DIR="/var/log/ceph-api"
DATA_DIR="/opt/ceph-api/data"
SERVICE_USER="ceph-api"
SERVICE_GROUP="ceph-api"
PYTHON_VERSION="3.11"

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_help() {
    cat << EOF
Ceph Management REST API - Installation Script

Usage: sudo $0 [OPTIONS]

Options:
    -h, --help              Show this help message
    -d, --install-dir DIR   Installation directory (default: /opt/ceph-api)
    -u, --user USER         Service user (default: ceph-api)
    -p, --port PORT         API port (default: 8080)
    --skip-firewall         Skip firewall configuration
    --skip-service-start    Install but don't start the service

Examples:
    sudo $0
    sudo $0 --skip-firewall
    sudo $0 --install-dir /opt/my-ceph-api

EOF
    exit 0
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        echo "Please run: sudo $0"
        exit 1
    fi
}

check_os() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "Cannot detect OS. This script supports Ubuntu/Debian only."
        exit 1
    fi

    . /etc/os-release
    if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
        log_error "Unsupported OS: $ID. This script supports Ubuntu/Debian only."
        exit 1
    fi

    log_info "Detected OS: $PRETTY_NAME"
}

install_dependencies() {
    log_info "Installing system dependencies..."

    apt-get update -qq

    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-rados \
        python3-cephfs \
        python3-rbd \
        ceph-common \
        sqlite3 \
        curl \
        ca-certificates \
        || { log_error "Failed to install dependencies"; exit 1; }

    log_success "Dependencies installed successfully"
}

create_user() {
    log_info "Creating service user: $SERVICE_USER"

    if id "$SERVICE_USER" &>/dev/null; then
        log_warning "User $SERVICE_USER already exists"
    else
        useradd --system \
                --no-create-home \
                --shell /usr/sbin/nologin \
                --comment "Ceph API Service User" \
                --user-group \
                "$SERVICE_USER"
        log_success "User $SERVICE_USER created"
    fi

    # Add user to ceph group for /etc/ceph access
    if getent group ceph &>/dev/null; then
        usermod -a -G ceph "$SERVICE_USER"
        log_success "Added $SERVICE_USER to ceph group"
    else
        log_warning "ceph group not found. User may not have access to Ceph config."
    fi
}

create_directories() {
    log_info "Creating application directories..."

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$LOG_DIR"
    mkdir -p "$INSTALL_DIR/app"
    mkdir -p "$INSTALL_DIR/config"

    log_success "Directories created"
}

copy_application_files() {
    log_info "Copying application files..."

    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

    if [[ ! -d "$PROJECT_ROOT/app" ]]; then
        log_error "Application source not found at $PROJECT_ROOT/app"
        log_error "Please run this script from the project directory"
        exit 1
    fi

    # Copy application code
    cp -r "$PROJECT_ROOT/app" "$INSTALL_DIR/"

    # Copy requirements.txt if exists
    if [[ -f "$PROJECT_ROOT/requirements.txt" ]]; then
        cp "$PROJECT_ROOT/requirements.txt" "$INSTALL_DIR/"
    fi

    # Copy config template if exists
    if [[ -f "$PROJECT_ROOT/config/config.yaml.example" ]]; then
        cp "$PROJECT_ROOT/config/config.yaml.example" "$INSTALL_DIR/config/"
        if [[ ! -f "$INSTALL_DIR/config/config.yaml" ]]; then
            cp "$PROJECT_ROOT/config/config.yaml.example" "$INSTALL_DIR/config/config.yaml"
            log_info "Created default config.yaml from example"
        fi
    fi

    log_success "Application files copied"
}

setup_virtualenv() {
    log_info "Creating Python virtual environment..."

    python3 -m venv "$INSTALL_DIR/venv"

    log_info "Upgrading pip..."
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip setuptools wheel -q

    log_success "Virtual environment created"
}

install_python_dependencies() {
    log_info "Installing Python dependencies..."

    if [[ -f "$INSTALL_DIR/requirements.txt" ]]; then
        "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
        log_success "Python dependencies installed"
    else
        log_warning "requirements.txt not found, installing basic dependencies..."
        "$INSTALL_DIR/venv/bin/pip" install \
            fastapi \
            uvicorn[standard] \
            python-rados \
            pyyaml \
            pydantic \
            pydantic-settings \
            sqlalchemy \
            aiosqlite \
            python-jose[cryptography] \
            passlib \
            bcrypt \
            httpx \
            -q
        log_success "Basic dependencies installed"
    fi
}

set_permissions() {
    log_info "Setting file permissions..."

    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$DATA_DIR"
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$LOG_DIR"

    chmod 750 "$INSTALL_DIR"
    chmod 750 "$DATA_DIR"
    chmod 750 "$LOG_DIR"
    chmod 640 "$INSTALL_DIR/config/config.yaml" 2>/dev/null || true

    # Allow read access to /etc/ceph if it exists
    if [[ -d /etc/ceph ]]; then
        if [[ -f /etc/ceph/ceph.conf ]]; then
            chmod 644 /etc/ceph/ceph.conf
        fi
        if [[ -f /etc/ceph/ceph.client.admin.keyring ]]; then
            chmod 640 /etc/ceph/ceph.client.admin.keyring
            chgrp ceph /etc/ceph/ceph.client.admin.keyring 2>/dev/null || true
        fi
    fi

    log_success "Permissions set"
}

initialize_database() {
    log_info "Initializing databases..."

    # Create empty SQLite databases
    sudo -u "$SERVICE_USER" touch "$DATA_DIR/api_keys.db"
    sudo -u "$SERVICE_USER" touch "$DATA_DIR/audit.db"

    # Run database initialization if script exists
    if [[ -f "$INSTALL_DIR/app/init_db.py" ]]; then
        sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/app/init_db.py"
        log_success "Database initialized"
    else
        log_warning "Database initialization script not found"
    fi
}

create_admin_api_key() {
    log_info "Creating initial admin API key..."

    # Generate a secure random API key
    ADMIN_API_KEY=$(openssl rand -hex 32)

    # Store the key using Python script if available
    if [[ -f "$INSTALL_DIR/app/create_api_key.py" ]]; then
        sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/app/create_api_key.py" \
            --name "admin" \
            --key "$ADMIN_API_KEY" \
            --role "admin"
    fi

    # Save to a secure file
    echo "$ADMIN_API_KEY" > /root/.ceph-api-admin-key
    chmod 600 /root/.ceph-api-admin-key

    log_success "Admin API key created"
    echo ""
    echo -e "${GREEN}================================================${NC}"
    echo -e "${GREEN}  ADMIN API KEY (save this securely):${NC}"
    echo -e "${YELLOW}  $ADMIN_API_KEY${NC}"
    echo -e "${GREEN}================================================${NC}"
    echo ""
    echo "This key has been saved to: /root/.ceph-api-admin-key"
    echo ""
}

install_systemd_service() {
    log_info "Installing systemd service..."

    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

    if [[ -f "$PROJECT_ROOT/systemd/ceph-api.service" ]]; then
        cp "$PROJECT_ROOT/systemd/ceph-api.service" /etc/systemd/system/
        systemctl daemon-reload
        log_success "Systemd service installed"
    else
        log_error "Systemd service file not found at $PROJECT_ROOT/systemd/ceph-api.service"
        exit 1
    fi
}

configure_firewall() {
    log_info "Configuring firewall..."

    read -p "Enter WHMCS server IP address (or press Enter to skip): " WHMCS_IP

    if [[ -z "$WHMCS_IP" ]]; then
        log_warning "Skipping firewall configuration"
        return
    fi

    if command -v ufw &> /dev/null; then
        ufw allow from "$WHMCS_IP" to any port 8080 proto tcp comment "Ceph API - WHMCS"
        log_success "UFW rule added for $WHMCS_IP"
    elif command -v iptables &> /dev/null; then
        SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
        PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

        if [[ -f "$PROJECT_ROOT/firewall/iptables-rules.sh" ]]; then
            bash "$PROJECT_ROOT/firewall/iptables-rules.sh" "$WHMCS_IP"
            log_success "iptables rules configured"
        else
            log_warning "iptables rules script not found"
        fi
    else
        log_warning "No supported firewall found (ufw or iptables)"
    fi
}

start_service() {
    log_info "Enabling and starting ceph-api service..."

    systemctl enable ceph-api.service
    systemctl start ceph-api.service

    sleep 3

    if systemctl is-active --quiet ceph-api.service; then
        log_success "Service started successfully"
        systemctl status ceph-api.service --no-pager -l
    else
        log_error "Service failed to start"
        journalctl -u ceph-api.service -n 50 --no-pager
        exit 1
    fi
}

verify_installation() {
    log_info "Verifying installation..."

    # Check if service is running
    if systemctl is-active --quiet ceph-api.service; then
        log_success "Service is running"
    else
        log_error "Service is not running"
        return 1
    fi

    # Check if API is responding
    sleep 2
    if curl -s -o /dev/null -w "%{http_code}" http://10.10.2.20:8080/health | grep -q "200"; then
        log_success "API health check passed"
    else
        log_warning "API health check failed (this may be normal if authentication is required)"
    fi
}

print_summary() {
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  Ceph Management REST API Installation Complete${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo "Installation directory: $INSTALL_DIR"
    echo "Data directory:         $DATA_DIR"
    echo "Log directory:          $LOG_DIR"
    echo "Service user:           $SERVICE_USER"
    echo "API endpoint:           http://10.10.2.20:8080"
    echo ""
    echo "Useful commands:"
    echo "  - View service status:  systemctl status ceph-api"
    echo "  - View logs:            journalctl -u ceph-api -f"
    echo "  - Restart service:      systemctl restart ceph-api"
    echo "  - Stop service:         systemctl stop ceph-api"
    echo ""
    echo "Next steps:"
    echo "  1. Review and update config: $INSTALL_DIR/config/config.yaml"
    echo "  2. Configure your WHMCS server to use the API"
    echo "  3. Monitor logs for any issues"
    echo ""
}

# Main installation flow
main() {
    SKIP_FIREWALL=false
    SKIP_SERVICE_START=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                ;;
            --skip-firewall)
                SKIP_FIREWALL=true
                shift
                ;;
            --skip-service-start)
                SKIP_SERVICE_START=true
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                ;;
        esac
    done

    log_info "Starting Ceph Management REST API installation..."
    echo ""

    check_root
    check_os
    install_dependencies
    create_user
    create_directories
    copy_application_files
    setup_virtualenv
    install_python_dependencies
    set_permissions
    initialize_database
    create_admin_api_key
    install_systemd_service

    if [[ "$SKIP_FIREWALL" == false ]]; then
        configure_firewall
    fi

    if [[ "$SKIP_SERVICE_START" == false ]]; then
        start_service
        verify_installation
    fi

    print_summary

    log_success "Installation completed successfully!"
}

# Run main function
main "$@"
