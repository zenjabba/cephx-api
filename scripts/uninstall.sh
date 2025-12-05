#!/bin/bash
#
# Ceph Management REST API - Uninstallation Script
# This script removes the Ceph API service from the system
#
# Usage: sudo ./uninstall.sh
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
SERVICE_USER="ceph-api"
SERVICE_NAME="ceph-api"

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
Ceph Management REST API - Uninstallation Script

Usage: sudo $0 [OPTIONS]

Options:
    -h, --help              Show this help message
    -f, --force             Skip confirmation prompts
    --keep-data             Keep application data directory
    --keep-logs             Keep log files
    --keep-user             Keep service user account

Examples:
    sudo $0
    sudo $0 --force
    sudo $0 --keep-data --keep-logs

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

confirm_uninstall() {
    if [[ "$FORCE" == true ]]; then
        return 0
    fi

    echo ""
    echo -e "${RED}WARNING: This will remove the Ceph Management REST API${NC}"
    echo ""
    echo "The following will be removed:"
    echo "  - Systemd service"
    echo "  - Application files in $INSTALL_DIR"
    if [[ "$KEEP_DATA" == false ]]; then
        echo "  - Data directory (including databases)"
    fi
    if [[ "$KEEP_LOGS" == false ]]; then
        echo "  - Log files in $LOG_DIR"
    fi
    if [[ "$KEEP_USER" == false ]]; then
        echo "  - Service user: $SERVICE_USER"
    fi
    echo ""

    read -p "Are you sure you want to continue? (yes/no): " response

    if [[ "$response" != "yes" ]]; then
        log_info "Uninstallation cancelled"
        exit 0
    fi
}

stop_service() {
    log_info "Stopping $SERVICE_NAME service..."

    if systemctl is-active --quiet "$SERVICE_NAME.service"; then
        systemctl stop "$SERVICE_NAME.service"
        log_success "Service stopped"
    else
        log_warning "Service is not running"
    fi
}

disable_service() {
    log_info "Disabling $SERVICE_NAME service..."

    if systemctl is-enabled --quiet "$SERVICE_NAME.service" 2>/dev/null; then
        systemctl disable "$SERVICE_NAME.service"
        log_success "Service disabled"
    else
        log_warning "Service is not enabled"
    fi
}

remove_systemd_service() {
    log_info "Removing systemd service file..."

    if [[ -f "/etc/systemd/system/$SERVICE_NAME.service" ]]; then
        rm -f "/etc/systemd/system/$SERVICE_NAME.service"
        systemctl daemon-reload
        systemctl reset-failed
        log_success "Systemd service file removed"
    else
        log_warning "Systemd service file not found"
    fi
}

backup_data() {
    if [[ "$KEEP_DATA" == false && -d "$INSTALL_DIR/data" ]]; then
        log_info "Creating backup of data before removal..."

        BACKUP_DIR="/root/ceph-api-backup-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP_DIR"

        if [[ -d "$INSTALL_DIR/data" ]]; then
            cp -r "$INSTALL_DIR/data" "$BACKUP_DIR/"
        fi

        if [[ -f "$INSTALL_DIR/config/config.yaml" ]]; then
            mkdir -p "$BACKUP_DIR/config"
            cp "$INSTALL_DIR/config/config.yaml" "$BACKUP_DIR/config/"
        fi

        log_success "Backup created at: $BACKUP_DIR"
    fi
}

remove_application_files() {
    log_info "Removing application files..."

    if [[ -d "$INSTALL_DIR" ]]; then
        if [[ "$KEEP_DATA" == true && -d "$INSTALL_DIR/data" ]]; then
            log_info "Preserving data directory..."
            DATA_BACKUP="/tmp/ceph-api-data-backup-$$"
            mv "$INSTALL_DIR/data" "$DATA_BACKUP"
            rm -rf "$INSTALL_DIR"
            mkdir -p "$INSTALL_DIR"
            mv "$DATA_BACKUP" "$INSTALL_DIR/data"
            log_success "Application files removed (data preserved)"
        else
            rm -rf "$INSTALL_DIR"
            log_success "Application files removed"
        fi
    else
        log_warning "Installation directory not found"
    fi
}

remove_log_files() {
    if [[ "$KEEP_LOGS" == false ]]; then
        log_info "Removing log files..."

        if [[ -d "$LOG_DIR" ]]; then
            rm -rf "$LOG_DIR"
            log_success "Log files removed"
        else
            log_warning "Log directory not found"
        fi
    else
        log_info "Preserving log files"
    fi
}

remove_user() {
    if [[ "$KEEP_USER" == false ]]; then
        log_info "Removing service user: $SERVICE_USER"

        if id "$SERVICE_USER" &>/dev/null; then
            userdel "$SERVICE_USER" 2>/dev/null || true

            # Remove group if it exists and is empty
            if getent group "$SERVICE_USER" &>/dev/null; then
                groupdel "$SERVICE_USER" 2>/dev/null || true
            fi

            log_success "Service user removed"
        else
            log_warning "Service user does not exist"
        fi
    else
        log_info "Preserving service user"
    fi
}

remove_firewall_rules() {
    log_info "Removing firewall rules..."

    if command -v ufw &> /dev/null; then
        # Find and remove UFW rules for port 8080 with Ceph API comment
        ufw status numbered | grep "8080.*Ceph API" | while read -r line; do
            ufw delete allow 8080/tcp 2>/dev/null || true
        done
        log_success "UFW rules removed (if any)"
    elif command -v iptables &> /dev/null; then
        # Remove iptables rules for port 8080
        iptables -D INPUT -p tcp --dport 8080 -j ACCEPT 2>/dev/null || true
        iptables -D INPUT -p tcp --dport 8080 -j DROP 2>/dev/null || true

        if command -v netfilter-persistent &> /dev/null; then
            netfilter-persistent save
        elif command -v iptables-save &> /dev/null; then
            iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
        fi

        log_success "iptables rules removed (if any)"
    else
        log_warning "No supported firewall found"
    fi
}

remove_environment_file() {
    log_info "Removing environment file..."

    if [[ -f "/etc/default/ceph-api" ]]; then
        rm -f "/etc/default/ceph-api"
        log_success "Environment file removed"
    fi
}

remove_admin_key_file() {
    log_info "Removing admin API key file..."

    if [[ -f "/root/.ceph-api-admin-key" ]]; then
        rm -f "/root/.ceph-api-admin-key"
        log_success "Admin key file removed"
    fi
}

print_summary() {
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  Uninstallation Complete${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""

    if [[ "$KEEP_DATA" == true ]]; then
        echo -e "${YELLOW}Data directory preserved:${NC} $INSTALL_DIR/data"
    fi

    if [[ "$KEEP_LOGS" == true ]]; then
        echo -e "${YELLOW}Log files preserved:${NC} $LOG_DIR"
    fi

    if [[ "$KEEP_USER" == true ]]; then
        echo -e "${YELLOW}Service user preserved:${NC} $SERVICE_USER"
    fi

    if [[ -d "/root/ceph-api-backup-"* ]]; then
        echo ""
        echo "Backup created at: $(ls -dt /root/ceph-api-backup-* | head -1)"
    fi

    echo ""
}

# Main uninstallation flow
main() {
    FORCE=false
    KEEP_DATA=false
    KEEP_LOGS=false
    KEEP_USER=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                ;;
            -f|--force)
                FORCE=true
                shift
                ;;
            --keep-data)
                KEEP_DATA=true
                shift
                ;;
            --keep-logs)
                KEEP_LOGS=true
                shift
                ;;
            --keep-user)
                KEEP_USER=true
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                ;;
        esac
    done

    log_info "Starting Ceph Management REST API uninstallation..."
    echo ""

    check_root
    confirm_uninstall
    backup_data
    stop_service
    disable_service
    remove_systemd_service
    remove_firewall_rules
    remove_application_files
    remove_log_files
    remove_environment_file
    remove_admin_key_file
    remove_user

    print_summary

    log_success "Uninstallation completed successfully!"
}

# Run main function
main "$@"
