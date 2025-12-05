#!/bin/bash
#
# Ceph Management REST API - Backup Script
# This script creates backups of the Ceph API databases and configuration
#
# Usage: ./backup.sh [OPTIONS]
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
BACKUP_BASE_DIR="/var/backups/ceph-api"
REMOTE_BACKUP_HOST=""
REMOTE_BACKUP_PATH=""
MAX_LOCAL_BACKUPS=14
MAX_REMOTE_BACKUPS=30

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
Ceph Management REST API - Backup Script

Usage: $0 [OPTIONS]

Options:
    -h, --help              Show this help message
    -d, --backup-dir DIR    Backup directory (default: /var/backups/ceph-api)
    -r, --remote HOST:PATH  Copy backup to remote location via rsync
    -c, --compress          Use gzip compression (default: enabled)
    -n, --name NAME         Custom backup name suffix
    --no-config             Skip configuration backup
    --no-databases          Skip database backup
    --verify                Verify backup integrity after creation
    --retention DAYS        Number of days to keep backups (default: 14)

Examples:
    $0
    $0 --remote backup-server:/backups/ceph-api
    $0 --name "pre-upgrade" --verify
    $0 --retention 30

EOF
    exit 0
}

check_directories() {
    log_info "Checking source directories..."

    if [[ ! -d "$INSTALL_DIR" ]]; then
        log_error "Installation directory not found: $INSTALL_DIR"
        exit 1
    fi

    if [[ ! -d "$DATA_DIR" ]] && [[ "$SKIP_DATABASES" == false ]]; then
        log_warning "Data directory not found: $DATA_DIR"
    fi

    if [[ ! -d "$CONFIG_DIR" ]] && [[ "$SKIP_CONFIG" == false ]]; then
        log_warning "Config directory not found: $CONFIG_DIR"
    fi

    log_success "Source directories verified"
}

create_backup_directory() {
    log_info "Creating backup directory..."

    TIMESTAMP=$(date +%Y%m%d-%H%M%S)

    if [[ -n "$CUSTOM_NAME" ]]; then
        BACKUP_NAME="backup-${TIMESTAMP}-${CUSTOM_NAME}"
    else
        BACKUP_NAME="backup-${TIMESTAMP}"
    fi

    BACKUP_DIR="$BACKUP_BASE_DIR/$BACKUP_NAME"

    mkdir -p "$BACKUP_DIR"
    mkdir -p "$BACKUP_DIR/data"
    mkdir -p "$BACKUP_DIR/config"
    mkdir -p "$BACKUP_DIR/metadata"

    log_success "Backup directory created: $BACKUP_DIR"
}

backup_databases() {
    if [[ "$SKIP_DATABASES" == true ]]; then
        log_warning "Skipping database backup (--no-databases specified)"
        return 0
    fi

    log_info "Backing up databases..."

    BACKED_UP_COUNT=0

    # Backup SQLite databases
    if [[ -f "$DATA_DIR/api_keys.db" ]]; then
        cp "$DATA_DIR/api_keys.db" "$BACKUP_DIR/data/"

        # Also create a SQL dump for portability
        if command -v sqlite3 &> /dev/null; then
            sqlite3 "$DATA_DIR/api_keys.db" .dump > "$BACKUP_DIR/data/api_keys.sql"
        fi

        BACKED_UP_COUNT=$((BACKED_UP_COUNT + 1))
        log_success "Backed up api_keys.db"
    fi

    if [[ -f "$DATA_DIR/audit.db" ]]; then
        cp "$DATA_DIR/audit.db" "$BACKUP_DIR/data/"

        if command -v sqlite3 &> /dev/null; then
            sqlite3 "$DATA_DIR/audit.db" .dump > "$BACKUP_DIR/data/audit.sql"
        fi

        BACKED_UP_COUNT=$((BACKED_UP_COUNT + 1))
        log_success "Backed up audit.db"
    fi

    # Backup any other .db files
    find "$DATA_DIR" -maxdepth 1 -name "*.db" -type f | while read -r dbfile; do
        dbname=$(basename "$dbfile")
        if [[ "$dbname" != "api_keys.db" && "$dbname" != "audit.db" ]]; then
            cp "$dbfile" "$BACKUP_DIR/data/"
            BACKED_UP_COUNT=$((BACKED_UP_COUNT + 1))
            log_success "Backed up $dbname"
        fi
    done

    if [[ $BACKED_UP_COUNT -eq 0 ]]; then
        log_warning "No databases found to backup"
    else
        log_success "Backed up $BACKED_UP_COUNT database(s)"
    fi
}

backup_configuration() {
    if [[ "$SKIP_CONFIG" == true ]]; then
        log_warning "Skipping configuration backup (--no-config specified)"
        return 0
    fi

    log_info "Backing up configuration files..."

    # Backup main config file
    if [[ -f "$CONFIG_DIR/config.yaml" ]]; then
        cp "$CONFIG_DIR/config.yaml" "$BACKUP_DIR/config/"
        log_success "Backed up config.yaml"
    fi

    # Backup any other config files
    if [[ -d "$CONFIG_DIR" ]]; then
        find "$CONFIG_DIR" -maxdepth 1 -type f | while read -r conffile; do
            confname=$(basename "$conffile")
            if [[ "$confname" != "config.yaml" ]]; then
                cp "$conffile" "$BACKUP_DIR/config/"
                log_success "Backed up $confname"
            fi
        done
    fi

    # Backup systemd service file
    if [[ -f "/etc/systemd/system/ceph-api.service" ]]; then
        cp "/etc/systemd/system/ceph-api.service" "$BACKUP_DIR/config/"
        log_success "Backed up systemd service file"
    fi

    # Backup environment file if exists
    if [[ -f "/etc/default/ceph-api" ]]; then
        cp "/etc/default/ceph-api" "$BACKUP_DIR/config/"
        log_success "Backed up environment file"
    fi
}

create_metadata() {
    log_info "Creating backup metadata..."

    cat > "$BACKUP_DIR/metadata/backup.info" << EOF
Backup Information
==================

Backup Date: $(date)
Backup Name: $BACKUP_NAME
Hostname: $(hostname)
Installation Directory: $INSTALL_DIR

Version Information
-------------------
EOF

    if [[ -f "$INSTALL_DIR/VERSION" ]]; then
        echo "Application Version: $(cat "$INSTALL_DIR/VERSION")" >> "$BACKUP_DIR/metadata/backup.info"
    fi

    echo "Python Version: $(python3 --version)" >> "$BACKUP_DIR/metadata/backup.info"

    cat >> "$BACKUP_DIR/metadata/backup.info" << EOF

Service Status
--------------
EOF

    if systemctl is-active --quiet ceph-api.service; then
        echo "Service Status: Running" >> "$BACKUP_DIR/metadata/backup.info"
    else
        echo "Service Status: Stopped" >> "$BACKUP_DIR/metadata/backup.info"
    fi

    cat >> "$BACKUP_DIR/metadata/backup.info" << EOF

Backup Contents
---------------
EOF

    find "$BACKUP_DIR" -type f | sed "s|$BACKUP_DIR/||" >> "$BACKUP_DIR/metadata/backup.info"

    # Create file checksums
    log_info "Generating checksums..."
    find "$BACKUP_DIR" -type f ! -path "*/metadata/*" -exec sha256sum {} \; > "$BACKUP_DIR/metadata/checksums.txt"

    log_success "Metadata created"
}

compress_backup() {
    if [[ "$USE_COMPRESSION" == false ]]; then
        log_info "Compression disabled"
        FINAL_BACKUP_PATH="$BACKUP_DIR"
        return 0
    fi

    log_info "Compressing backup..."

    ARCHIVE_PATH="$BACKUP_BASE_DIR/${BACKUP_NAME}.tar.gz"

    tar -czf "$ARCHIVE_PATH" -C "$BACKUP_BASE_DIR" "$BACKUP_NAME"

    # Remove uncompressed directory
    rm -rf "$BACKUP_DIR"

    BACKUP_SIZE=$(du -h "$ARCHIVE_PATH" | cut -f1)

    log_success "Backup compressed: $ARCHIVE_PATH (${BACKUP_SIZE})"

    FINAL_BACKUP_PATH="$ARCHIVE_PATH"
}

verify_backup() {
    if [[ "$VERIFY_BACKUP" == false ]]; then
        return 0
    fi

    log_info "Verifying backup integrity..."

    if [[ "$USE_COMPRESSION" == true ]]; then
        # Verify tar archive
        if tar -tzf "$FINAL_BACKUP_PATH" &>/dev/null; then
            log_success "Archive integrity verified"
        else
            log_error "Archive verification failed!"
            exit 1
        fi
    else
        # Verify checksums
        if [[ -f "$BACKUP_DIR/metadata/checksums.txt" ]]; then
            cd "$BACKUP_DIR"
            if sha256sum -c metadata/checksums.txt --quiet 2>/dev/null; then
                log_success "Checksum verification passed"
            else
                log_error "Checksum verification failed!"
                exit 1
            fi
        fi
    fi
}

copy_to_remote() {
    if [[ -z "$REMOTE_BACKUP_HOST" ]]; then
        return 0
    fi

    log_info "Copying backup to remote location: $REMOTE_BACKUP_HOST:$REMOTE_BACKUP_PATH"

    if ! command -v rsync &> /dev/null; then
        log_error "rsync is not installed. Cannot copy to remote location."
        return 1
    fi

    # Create remote directory if needed
    ssh "$REMOTE_BACKUP_HOST" "mkdir -p $REMOTE_BACKUP_PATH" || {
        log_error "Failed to create remote directory"
        return 1
    }

    # Copy backup
    rsync -avz --progress "$FINAL_BACKUP_PATH" "$REMOTE_BACKUP_HOST:$REMOTE_BACKUP_PATH/" || {
        log_error "Failed to copy backup to remote location"
        return 1
    }

    log_success "Backup copied to remote location"

    # Clean up old remote backups
    if [[ $MAX_REMOTE_BACKUPS -gt 0 ]]; then
        log_info "Cleaning up old remote backups (keeping last $MAX_REMOTE_BACKUPS)..."
        ssh "$REMOTE_BACKUP_HOST" "cd $REMOTE_BACKUP_PATH && ls -t backup-*.tar.gz 2>/dev/null | tail -n +$((MAX_REMOTE_BACKUPS + 1)) | xargs rm -f"
    fi
}

cleanup_old_backups() {
    log_info "Cleaning up old backups (keeping last $MAX_LOCAL_BACKUPS)..."

    if [[ "$USE_COMPRESSION" == true ]]; then
        BACKUP_COUNT=$(ls -1 "$BACKUP_BASE_DIR"/backup-*.tar.gz 2>/dev/null | wc -l)

        if [[ $BACKUP_COUNT -gt $MAX_LOCAL_BACKUPS ]]; then
            ls -1t "$BACKUP_BASE_DIR"/backup-*.tar.gz | tail -n +$((MAX_LOCAL_BACKUPS + 1)) | xargs rm -f
            REMOVED=$((BACKUP_COUNT - MAX_LOCAL_BACKUPS))
            log_success "Removed $REMOVED old backup(s)"
        fi
    else
        BACKUP_COUNT=$(ls -1d "$BACKUP_BASE_DIR"/backup-* 2>/dev/null | wc -l)

        if [[ $BACKUP_COUNT -gt $MAX_LOCAL_BACKUPS ]]; then
            ls -1dt "$BACKUP_BASE_DIR"/backup-* | tail -n +$((MAX_LOCAL_BACKUPS + 1)) | xargs rm -rf
            REMOVED=$((BACKUP_COUNT - MAX_LOCAL_BACKUPS))
            log_success "Removed $REMOVED old backup(s)"
        fi
    fi
}

print_summary() {
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  Backup Complete${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo "Backup location: $FINAL_BACKUP_PATH"

    if [[ -f "$FINAL_BACKUP_PATH" ]]; then
        BACKUP_SIZE=$(du -h "$FINAL_BACKUP_PATH" | cut -f1)
        echo "Backup size:     $BACKUP_SIZE"
    fi

    if [[ -n "$REMOTE_BACKUP_HOST" ]]; then
        echo "Remote location: $REMOTE_BACKUP_HOST:$REMOTE_BACKUP_PATH"
    fi

    echo ""
    echo "To restore from this backup:"
    if [[ "$USE_COMPRESSION" == true ]]; then
        echo "  tar -xzf $FINAL_BACKUP_PATH -C /tmp"
        echo "  # Then manually restore files to $INSTALL_DIR"
    else
        echo "  # Manually restore files from $FINAL_BACKUP_PATH"
    fi
    echo ""
}

# Main backup flow
main() {
    USE_COMPRESSION=true
    SKIP_CONFIG=false
    SKIP_DATABASES=false
    VERIFY_BACKUP=false
    CUSTOM_NAME=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                ;;
            -d|--backup-dir)
                BACKUP_BASE_DIR="$2"
                shift 2
                ;;
            -r|--remote)
                IFS=':' read -r REMOTE_BACKUP_HOST REMOTE_BACKUP_PATH <<< "$2"
                shift 2
                ;;
            -c|--compress)
                USE_COMPRESSION=true
                shift
                ;;
            -n|--name)
                CUSTOM_NAME="$2"
                shift 2
                ;;
            --no-config)
                SKIP_CONFIG=true
                shift
                ;;
            --no-databases)
                SKIP_DATABASES=true
                shift
                ;;
            --verify)
                VERIFY_BACKUP=true
                shift
                ;;
            --retention)
                MAX_LOCAL_BACKUPS="$2"
                shift 2
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                ;;
        esac
    done

    log_info "Starting Ceph Management REST API backup..."
    echo ""

    check_directories
    create_backup_directory
    backup_databases
    backup_configuration
    create_metadata
    compress_backup
    verify_backup
    copy_to_remote
    cleanup_old_backups

    print_summary

    log_success "Backup completed successfully!"
}

# Run main function
main "$@"
