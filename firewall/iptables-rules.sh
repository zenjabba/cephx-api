#!/bin/bash
#
# Ceph Management REST API - iptables Firewall Rules
# This script configures firewall rules for the Ceph API service
#
# Usage: sudo ./iptables-rules.sh [WHMCS_IP]
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
API_PORT=8080
SERVICE_NAME="Ceph API"

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
Ceph Management REST API - iptables Firewall Rules

Usage: sudo $0 [OPTIONS] [WHMCS_IP]

Arguments:
    WHMCS_IP                IP address of WHMCS server to allow access

Options:
    -h, --help              Show this help message
    -p, --port PORT         API port (default: 8080)
    -a, --allow IP          Add allowed IP address (can be used multiple times)
    -d, --delete            Delete existing rules
    -l, --list              List current rules
    --allow-all             Allow access from all IPs (not recommended)

Examples:
    sudo $0 10.10.1.100
    sudo $0 --allow 10.10.1.100 --allow 10.10.1.101
    sudo $0 --delete
    sudo $0 --list

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

check_iptables() {
    if ! command -v iptables &> /dev/null; then
        log_error "iptables is not installed"
        exit 1
    fi
}

list_rules() {
    log_info "Current iptables rules for port $API_PORT:"
    echo ""

    iptables -L INPUT -n -v --line-numbers | grep -E "dpt:$API_PORT|Chain INPUT" || echo "No rules found"

    echo ""
}

delete_existing_rules() {
    log_info "Deleting existing rules for port $API_PORT..."

    # Get line numbers of rules matching our port (in reverse order)
    RULE_LINES=$(iptables -L INPUT -n --line-numbers | grep "dpt:$API_PORT" | awk '{print $1}' | sort -rn)

    if [[ -z "$RULE_LINES" ]]; then
        log_warning "No existing rules found for port $API_PORT"
        return 0
    fi

    # Delete rules in reverse order to maintain line numbers
    for line in $RULE_LINES; do
        iptables -D INPUT "$line"
        log_success "Deleted rule at line $line"
    done

    log_success "Existing rules deleted"
}

add_allow_rule() {
    local IP=$1

    # Validate IP address format
    if ! [[ "$IP" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        log_error "Invalid IP address format: $IP"
        return 1
    fi

    log_info "Adding allow rule for IP: $IP"

    # Check if rule already exists
    if iptables -C INPUT -p tcp -s "$IP" --dport "$API_PORT" -j ACCEPT 2>/dev/null; then
        log_warning "Rule already exists for $IP"
        return 0
    fi

    # Add the rule
    iptables -I INPUT -p tcp -s "$IP" --dport "$API_PORT" -j ACCEPT -m comment --comment "$SERVICE_NAME - Allow $IP"

    log_success "Added allow rule for $IP"
}

add_drop_rule() {
    log_info "Adding drop rule for all other IPs on port $API_PORT"

    # Check if drop rule already exists
    if iptables -C INPUT -p tcp --dport "$API_PORT" -j DROP 2>/dev/null; then
        log_warning "Drop rule already exists"
        return 0
    fi

    # Add drop rule at the end
    iptables -A INPUT -p tcp --dport "$API_PORT" -j DROP -m comment --comment "$SERVICE_NAME - Drop all others"

    log_success "Added drop rule"
}

add_allow_all_rule() {
    log_warning "Adding rule to allow access from ALL IPs (not recommended for production)"

    # Check if rule already exists
    if iptables -C INPUT -p tcp --dport "$API_PORT" -j ACCEPT 2>/dev/null; then
        log_warning "Allow all rule already exists"
        return 0
    fi

    iptables -I INPUT -p tcp --dport "$API_PORT" -j ACCEPT -m comment --comment "$SERVICE_NAME - Allow all"

    log_success "Added allow all rule"
}

save_rules() {
    log_info "Saving iptables rules..."

    # Try different methods to persist rules
    if command -v netfilter-persistent &> /dev/null; then
        netfilter-persistent save
        log_success "Rules saved with netfilter-persistent"
    elif command -v iptables-save &> /dev/null && [[ -d /etc/iptables ]]; then
        iptables-save > /etc/iptables/rules.v4
        log_success "Rules saved to /etc/iptables/rules.v4"
    elif command -v service &> /dev/null && service iptables status &>/dev/null; then
        service iptables save
        log_success "Rules saved with service iptables"
    else
        log_warning "Could not automatically save rules"
        log_warning "You may need to manually save iptables rules for persistence"
        log_info "Try installing: apt-get install iptables-persistent"
    fi
}

install_persistence_package() {
    log_info "Checking for iptables persistence package..."

    if command -v netfilter-persistent &> /dev/null; then
        log_success "netfilter-persistent is already installed"
        return 0
    fi

    log_warning "netfilter-persistent is not installed"
    read -p "Would you like to install iptables-persistent for rule persistence? (y/n): " response

    if [[ "$response" == "y" || "$response" == "Y" ]]; then
        log_info "Installing iptables-persistent..."

        # Pre-answer the package configuration prompts
        echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
        echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections

        DEBIAN_FRONTEND=noninteractive apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent

        log_success "iptables-persistent installed"
    else
        log_warning "Skipping iptables-persistent installation"
        log_warning "Rules may not persist after reboot"
    fi
}

print_summary() {
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}  Firewall Configuration Complete${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo "Current rules for port $API_PORT:"
    echo ""

    iptables -L INPUT -n -v --line-numbers | grep -E "dpt:$API_PORT|Chain INPUT" || echo "No rules found"

    echo ""
    echo "Commands:"
    echo "  - List rules:    iptables -L INPUT -n -v --line-numbers"
    echo "  - Delete rule:   iptables -D INPUT <line_number>"
    echo "  - Save rules:    netfilter-persistent save"
    echo ""
}

# Main function
main() {
    ALLOWED_IPS=()
    DELETE_RULES=false
    LIST_ONLY=false
    ALLOW_ALL=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                ;;
            -p|--port)
                API_PORT="$2"
                shift 2
                ;;
            -a|--allow)
                ALLOWED_IPS+=("$2")
                shift 2
                ;;
            -d|--delete)
                DELETE_RULES=true
                shift
                ;;
            -l|--list)
                LIST_ONLY=true
                shift
                ;;
            --allow-all)
                ALLOW_ALL=true
                shift
                ;;
            *)
                # Treat as IP address
                if [[ "$1" =~ ^[0-9] ]]; then
                    ALLOWED_IPS+=("$1")
                    shift
                else
                    log_error "Unknown option: $1"
                    show_help
                fi
                ;;
        esac
    done

    check_root
    check_iptables

    if [[ "$LIST_ONLY" == true ]]; then
        list_rules
        exit 0
    fi

    if [[ "$DELETE_RULES" == true ]]; then
        delete_existing_rules
        save_rules
        print_summary
        exit 0
    fi

    log_info "Configuring firewall rules for $SERVICE_NAME on port $API_PORT..."
    echo ""

    # Delete existing rules first
    delete_existing_rules

    # Add rules
    if [[ "$ALLOW_ALL" == true ]]; then
        add_allow_all_rule
    elif [[ ${#ALLOWED_IPS[@]} -eq 0 ]]; then
        log_warning "No IP addresses specified"
        read -p "Enter WHMCS server IP address (or 'all' to allow all): " input_ip

        if [[ "$input_ip" == "all" ]]; then
            add_allow_all_rule
        elif [[ -n "$input_ip" ]]; then
            ALLOWED_IPS+=("$input_ip")
        else
            log_error "No IP address provided"
            exit 1
        fi
    fi

    # Add allow rules for each IP
    for ip in "${ALLOWED_IPS[@]}"; do
        add_allow_rule "$ip"
    done

    # Add drop rule if not allowing all
    if [[ "$ALLOW_ALL" == false ]]; then
        add_drop_rule
    fi

    # Install persistence package if needed
    install_persistence_package

    # Save rules
    save_rules

    print_summary

    log_success "Firewall configuration completed!"
}

# Run main function
main "$@"
