#!/bin/bash

# CephX API Startup Script

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}CephX API - Ceph Management REST API${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_VERSION="3.11"

if [[ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]]; then
    echo -e "${RED}Error: Python 3.11+ required (found $PYTHON_VERSION)${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python version: $PYTHON_VERSION${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${BLUE}Creating virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "${BLUE}Installing dependencies...${NC}"
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo -e "${GREEN}✓ Dependencies installed${NC}"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${BLUE}Creating .env from .env.example...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✓ .env created (please configure before production use)${NC}"
fi

# Create log directory if it doesn't exist
LOG_DIR="/var/log/cephx-api"
if [ ! -d "$LOG_DIR" ]; then
    echo -e "${BLUE}Creating log directory...${NC}"
    sudo mkdir -p "$LOG_DIR"
    sudo chown $(whoami) "$LOG_DIR"
    echo -e "${GREEN}✓ Log directory created: $LOG_DIR${NC}"
fi

# Check for Ceph CLI
if ! command -v ceph &> /dev/null; then
    echo -e "${RED}Warning: 'ceph' command not found. Install Ceph CLI tools.${NC}"
else
    echo -e "${GREEN}✓ Ceph CLI available${NC}"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Starting CephX API...${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "API Documentation: ${GREEN}http://localhost:8000/docs${NC}"
echo -e "Health Check:      ${GREEN}http://localhost:8000/health${NC}"
echo ""

# Start the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
