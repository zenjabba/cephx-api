#!/bin/bash

# Verification script for CephFS API implementation

echo "========================================="
echo "CephFS API Implementation Verification"
echo "========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

ERRORS=0

check_file() {
    local file="$1"
    local desc="$2"
    
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $desc"
    else
        echo -e "${RED}✗${NC} $desc - MISSING: $file"
        ((ERRORS++))
    fi
}

echo -e "${BLUE}Core Implementation Files:${NC}"
check_file "app/routers/filesystem.py" "Filesystem router (main implementation)"
check_file "app/models/filesystem.py" "Filesystem models"
check_file "app/services/ceph_client.py" "Ceph client service"
check_file "app/core/auth.py" "Authentication middleware"
check_file "app/core/exceptions.py" "Custom exceptions"
check_file "app/core/logging.py" "Audit logging"
check_file "app/core/config.py" "Configuration"
check_file "app/main.py" "FastAPI application"
echo ""

echo -e "${BLUE}Documentation Files:${NC}"
check_file "README.md" "Main documentation"
check_file "QUICKSTART.md" "Quick start guide"
check_file "EXAMPLES.md" "API examples"
check_file "FILESYSTEM_API_IMPLEMENTATION.md" "Implementation summary"
echo ""

echo -e "${BLUE}Configuration Files:${NC}"
check_file "requirements.txt" "Python dependencies"
check_file ".env.example" "Environment template"
check_file "pyproject.toml" "Tool configuration"
echo ""

echo -e "${BLUE}Utility Files:${NC}"
check_file "run.sh" "Startup script"
check_file "tests/test_filesystem.py" "Test suite"
echo ""

# Check Python syntax
echo -e "${BLUE}Checking Python Syntax:${NC}"
if command -v python3 &> /dev/null; then
    for file in app/routers/filesystem.py app/services/ceph_client.py app/models/filesystem.py app/core/*.py; do
        if [ -f "$file" ]; then
            if python3 -m py_compile "$file" 2>/dev/null; then
                echo -e "${GREEN}✓${NC} $(basename $file) - syntax OK"
            else
                echo -e "${RED}✗${NC} $(basename $file) - SYNTAX ERROR"
                ((ERRORS++))
            fi
        fi
    done
else
    echo -e "${RED}✗${NC} Python3 not found - skipping syntax check"
fi
echo ""

# Count endpoints
echo -e "${BLUE}Endpoint Summary:${NC}"
if [ -f "app/routers/filesystem.py" ]; then
    echo "Implemented endpoints:"
    grep -E "@router\.(get|post|delete)" app/routers/filesystem.py | grep -v "^#" | while read line; do
        echo "  - $line"
    done
fi
echo ""

# Summary
echo "========================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Run: ./run.sh"
    echo "  2. Visit: http://localhost:8000/docs"
    echo "  3. Test with: curl http://localhost:8000/health"
else
    echo -e "${RED}✗ Found $ERRORS error(s)${NC}"
    exit 1
fi
echo "========================================="
