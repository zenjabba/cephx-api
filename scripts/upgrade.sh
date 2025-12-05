#!/bin/bash
#
# Ceph Management REST API - Upgrade Script
# This script upgrades the Ceph API service to a new version
#
# Usage: sudo ./upgrade.sh
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
BACKUP_DIR="/opt/ceph-api-backups"
SERVICE_NAME="ceph-api"
MAX_BACKUPS=5

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
Ceph Management REST API - Upgrade Script

Usage: sudo $0 [OPTIONS]

Options:
    -h, --help              Show this help message
    -f, --force             Skip confirmation prompts
    --skip-backup           Skip backup creation (not recommended)
    --skip-health-check     Skip post-upgrade health check
    --rollback              Rollback to previous version

Examples:
    sudo $0
    sudo $0 --force
    sudo $0 --rollback

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

check_installation() {
    log_info "Checking current installation..."

    if [[ ! -d "$INSTALL_DIR" ]]; then
        log_error "Installation directory not found: $INSTALL_DIR"
        log_error "Please install the application first using install.sh"
        exit 1
    fi

    if ! systemctl list-unit-files | grep -q "$SERVICE_NAME.service"; then
        log_error "Service $SERVICE_NAME not found"
        exit 1
    fi

    log_success "Current installation verified"
}

get_current_version() {
    if [[ -f "$INSTALL_DIR/VERSION" ]]; then
        CURRENT_VERSION=$(cat "$INSTALL_DIR/VERSION")
        log_info "Current version: $CURRENT_VERSION"
    else
        CURRENT_VERSION="unknown"
        log_warning "Current version unknown (VERSION file not found)"
    fi
}

confirm_upgrade() {
    if [[ "$FORCE" == true ]]; then
        return 0
    fi

    echo ""
    echo -e "${YELLOW}This will upgrade the Ceph Management REST API${NC}"
    echo ""
    echo "Current version: $CURRENT_VERSION"
    echo "Installation directory: $INSTALL_DIR"
    echo ""
    echo "The service will be temporarily stopped during the upgrade."
    echo "A backup will be created before proceeding."
    echo ""

    read -p "Do you want to continue? (yes/no): " response

    if [[ "$response" != "yes" ]]; then
        log_info "Upgrade cancelled"
        exit 0
    fi
}

create_backup() {
    if [[ "$SKIP_BACKUP" == true ]]; then
        log_warning "Skipping backup (--skip-backup specified)"
        return 0
    fi

    log_info "Creating backup of current installation..."

    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    BACKUP_PATH="$BACKUP_DIR/backup-$TIMESTAMP"

    mkdir -p "$BACKUP_DIR"
    mkdir -p "$BACKUP_PATH"

    # Backup application files
    if [[ -d "$INSTALL_DIR/app" ]]; then
        cp -r "$INSTALL_DIR/app" "$BACKUP_PATH/"
    fi

    # Backup configuration
    if [[ -f "$INSTALL_DIR/config/config.yaml" ]]; then
        mkdir -p "$BACKUP_PATH/config"
        cp "$INSTALL_DIR/config/config.yaml" "$BACKUP_PATH/config/"
    fi

    # Backup databases
    if [[ -d "$INSTALL_DIR/data" ]]; then
        cp -r "$INSTALL_DIR/data" "$BACKUP_PATH/"
    fi

    # Backup requirements.txt
    if [[ -f "$INSTALL_DIR/requirements.txt" ]]; then
        cp "$INSTALL_DIR/requirements.txt" "$BACKUP_PATH/"
    fi

    # Backup VERSION file
    if [[ -f "$INSTALL_DIR/VERSION" ]]; then
        cp "$INSTALL_DIR/VERSION" "$BACKUP_PATH/"
    fi

    # Create backup info file
    cat > "$BACKUP_PATH/backup.info" << EOF
Backup created: $TIMESTAMP
Version: $CURRENT_VERSION
Installation directory: $INSTALL_DIR
Service: $SERVICE_NAME
EOF

    log_success "Backup created at: $BACKUP_PATH"
    echo "$BACKUP_PATH" > /tmp/ceph-api-last-backup

    # Clean up old backups
    cleanup_old_backups
}

cleanup_old_backups() {
    log_info "Cleaning up old backups (keeping last $MAX_BACKUPS)..."

    BACKUP_COUNT=$(ls -1d "$BACKUP_DIR"/backup-* 2>/dev/null | wc -l)

    if [[ $BACKUP_COUNT -gt $MAX_BACKUPS ]]; then
        ls -1dt "$BACKUP_DIR"/backup-* | tail -n +$((MAX_BACKUPS + 1)) | xargs rm -rf
        log_success "Removed old backups"
    fi
}

stop_service() {
    log_info "Stopping $SERVICE_NAME service..."

    if systemctl is-active --quiet "$SERVICE_NAME.service"; then
        systemctl stop "$SERVICE_NAME.service"
        log_success "Service stopped"
    else
        log_warning "Service was not running"
    fi
}

update_application_files() {
    log_info "Updating application files..."

    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

    if [[ ! -d "$PROJECT_ROOT/app" ]]; then
        log_error "Application source not found at $PROJECT_ROOT/app"
        exit 1
    fi

    # Remove old application files (but preserve data and config)
    if [[ -d "$INSTALL_DIR/app" ]]; then
        rm -rf "$INSTALL_DIR/app"
    fi

    # Copy new application files
    cp -r "$PROJECT_ROOT/app" "$INSTALL_DIR/"

    # Update requirements.txt if exists
    if [[ -f "$PROJECT_ROOT/requirements.txt" ]]; then
        cp "$PROJECT_ROOT/requirements.txt" "$INSTALL_DIR/"
    fi

    # Update VERSION file if exists
    if [[ -f "$PROJECT_ROOT/VERSION" ]]; then
        cp "$PROJECT_ROOT/VERSION" "$INSTALL_DIR/"
        NEW_VERSION=$(cat "$INSTALL_DIR/VERSION")
        log_info "New version: $NEW_VERSION"
    fi

    # Update systemd service file if changed
    if [[ -f "$PROJECT_ROOT/systemd/ceph-api.service" ]]; then
        if ! diff -q "$PROJECT_ROOT/systemd/ceph-api.service" "/etc/systemd/system/$SERVICE_NAME.service" &>/dev/null; then
            log_info "Updating systemd service file..."
            cp "$PROJECT_ROOT/systemd/ceph-api.service" "/etc/systemd/system/"
            systemctl daemon-reload
            log_success "Systemd service file updated"
        fi
    fi

    log_success "Application files updated"
}

update_dependencies() {
    log_info "Updating Python dependencies..."

    if [[ -f "$INSTALL_DIR/requirements.txt" ]]; then
        "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
        "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --upgrade -q
        log_success "Dependencies updated"
    else
        log_warning "requirements.txt not found, skipping dependency update"
    fi
}

run_migrations() {
    log_info "Running database migrations..."

    if [[ -f "$INSTALL_DIR/app/migrate.py" ]]; then
        sudo -u ceph-api "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/app/migrate.py"
        log_success "Database migrations completed"
    else
        log_info "No migration script found, skipping"
    fi
}

set_permissions() {
    log_info "Setting file permissions..."

    chown -R ceph-api:ceph-api "$INSTALL_DIR/app"
    chmod 750 "$INSTALL_DIR/app"

    if [[ -f "$INSTALL_DIR/config/config.yaml" ]]; then
        chmod 640 "$INSTALL_DIR/config/config.yaml"
    fi

    log_success "Permissions set"
}

start_service() {
    log_info "Starting $SERVICE_NAME service..."

    systemctl start "$SERVICE_NAME.service"

    sleep 3

    if systemctl is-active --quiet "$SERVICE_NAME.service"; then
        log_success "Service started successfully"
    else
        log_error "Service failed to start"
        journalctl -u "$SERVICE_NAME.service" -n 50 --no-pager

        if [[ "$SKIP_BACKUP" == false ]]; then
            log_warning "Upgrade failed. You can rollback using: $0 --rollback"
        fi

        exit 1
    fi
}

verify_health() {
    if [[ "$SKIP_HEALTH_CHECK" == true ]]; then
        log_warning "Skipping health check (--skip-health-check specified)"
        return 0
    fi

    log_info "Verifying service health..."

    # Wait a bit for service to fully start
    sleep 5

    # Check service status
    if ! systemctl is-active --quiet "$SERVICE_NAME.service"; then
        log_error "Service is not running"
        return 1
    fi

    # Check API health endpoint
    MAX_RETRIES=5
    RETRY_COUNT=0

    while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
        if curl -s -f http://10.10.2.20:8080/health &>/dev/null; then
            log_success "Health check passed"
            return 0
        fi

        RETRY_COUNT=$((RETRY_COUNT + 1))
        log_info "Health check attempt $RETRY_COUNT/$MAX_RETRIES..."
        sleep 2
    done

    log_warning "Health check failed (API may require authentication)"
    log_info "Service is running, but health endpoint is not accessible"

    return 0
}

rollback_to_previous() {
    log_info "Rolling back to previous version..."

    if [[ ! -f /tmp/ceph-api-last-backup ]]; then
        log_error "No backup information found"
        log_error "Cannot perform automatic rollback"
        exit 1
    fi

    LAST_BACKUP=$(cat /tmp/ceph-api-last-backup)

    if [[ ! -d "$LAST_BACKUP" ]]; then
        log_error "Backup directory not found: $LAST_BACKUP"
        exit 1
    fi

    log_info "Restoring from backup: $LAST_BACKUP"

    # Stop service
    systemctl stop "$SERVICE_NAME.service"

    # Restore application files
    if [[ -d "$LAST_BACKUP/app" ]]; then
        rm -rf "$INSTALL_DIR/app"
        cp -r "$LAST_BACKUP/app" "$INSTALL_DIR/"
    fi

    # Restore configuration
    if [[ -f "$LAST_BACKUP/config/config.yaml" ]]; then
        cp "$LAST_BACKUP/config/config.yaml" "$INSTALL_DIR/config/"
    fi

    # Restore databases
    if [[ -d "$LAST_BACKUP/data" ]]; then
        rm -rf "$INSTALL_DIR/data"
        cp -r "$LAST_BACKUP/data" "$INSTALL_DIR/"
    fi

    # Restore requirements.txt
    if [[ -f "$LAST_BACKUP/requirements.txt" ]]; then
        cp "$LAST_BACKUP/requirements.txt" "$INSTALL_DIR/"
    fi

    # Restore VERSION
    if [[ -f "$LAST_BACKUP/VERSION" ]]; then
        cp "$LAST_BACKUP/VERSION" "$INSTALL_DIR/"
    fi

    # Set permissions
    chown -R ceph-api:ceph-api "$INSTALL_DIR"

    # Reinstall dependencies
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

    # Start service
    systemctl start "$SERVICE_NAME.service"

    sleep 3

    if systemctl is-active --quiet "$SERVICE_NAME.service"; then
        log_success "Rollback completed successfully"
    else
        log_error "Rollback failed - service did not start"
        exit 1
    fi
}

print_summary() {
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  Upgrade Complete${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""

    if [[ "$CURRENT_VERSION" != "unknown" && -f "$INSTALL_DIR/VERSION" ]]; then
        NEW_VERSION=$(cat "$INSTALL_DIR/VERSION")
        echo "Previous version: $CURRENT_VERSION"
        echo "New version:      $NEW_VERSION"
    fi

    echo ""
    echo "Useful commands:"
    echo "  - View service status:  systemctl status $SERVICE_NAME"
    echo "  - View logs:            journalctl -u $SERVICE_NAME -f"
    echo "  - Rollback:             $0 --rollback"
    echo ""
}

# Main upgrade flow
main() {
    FORCE=false
    SKIP_BACKUP=false
    SKIP_HEALTH_CHECK=false
    DO_ROLLBACK=false

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
            --skip-backup)
                SKIP_BACKUP=true
                shift
                ;;
            --skip-health-check)
                SKIP_HEALTH_CHECK=true
                shift
                ;;
            --rollback)
                DO_ROLLBACK=true
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                ;;
        esac
    done

    check_root

    if [[ "$DO_ROLLBACK" == true ]]; then
        rollback_to_previous
        exit 0
    fi

    log_info "Starting Ceph Management REST API upgrade..."
    echo ""

    check_installation
    get_current_version
    confirm_upgrade
    create_backup
    stop_service
    update_application_files
    update_dependencies
    run_migrations
    set_permissions
    start_service
    verify_health

    print_summary

    log_success "Upgrade completed successfully!"
}

# Run main function
main "$@"
