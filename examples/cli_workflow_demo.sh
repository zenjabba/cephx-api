#!/bin/bash
# Demonstration of complete CLI workflow for Ceph Management API

set -e

# Use temporary database for demo
export CEPHX_DB_PATH="/tmp/demo_cephx_api.db"

echo "========================================="
echo "Ceph Management API - CLI Workflow Demo"
echo "========================================="
echo ""

# Clean up any existing demo database
rm -f "$CEPHX_DB_PATH"

echo "Step 1: Initialize Database"
echo "----------------------------"
python -m app.cli init-db
echo ""

echo "Step 2: Create Production API Key"
echo "----------------------------------"
PROD_KEY=$(python -m app.cli create-api-key \
  --name "WHMCS Production" \
  --permissions "auth:read,auth:write,fs:read,fs:write,snapshot:read,snapshot:write,cluster:read" \
  --rate-limit 120 | grep -E "^(prod|api|admin|dev|test)_" | head -1)
echo "Generated key: $PROD_KEY"
echo ""

echo "Step 3: Create Monitoring Key (Read-Only)"
echo "------------------------------------------"
python -m app.cli create-api-key \
  --name "Monitoring Dashboard" \
  --permissions "auth:read,fs:read,snapshot:read,cluster:read" \
  --rate-limit 300
echo ""

echo "Step 4: Create Admin Key with Expiration"
echo "-----------------------------------------"
python -m app.cli create-api-key \
  --name "Admin Temporary" \
  --permissions "admin:*" \
  --rate-limit 1000 \
  --expires "2026-12-31T23:59:59Z"
echo ""

echo "Step 5: List All API Keys"
echo "-------------------------"
python -m app.cli list-api-keys
echo ""

echo "Step 6: Disable Admin Key"
echo "-------------------------"
python -m app.cli disable-api-key --name "Admin Temporary"
echo ""

echo "Step 7: List Keys (Including Disabled)"
echo "---------------------------------------"
python -m app.cli list-api-keys --show-disabled
echo ""

echo "Step 8: Re-enable Admin Key"
echo "---------------------------"
python -m app.cli enable-api-key --name "Admin Temporary"
echo ""

echo "Step 9: Delete Admin Key"
echo "------------------------"
python -m app.cli delete-api-key --confirm DELETE --name "Admin Temporary"
echo ""

echo "Step 10: Final Key List"
echo "-----------------------"
python -m app.cli list-api-keys
echo ""

echo "Step 11: View Audit Log (Empty)"
echo "--------------------------------"
python -m app.cli audit-log --limit 10
echo ""

echo "========================================="
echo "Demo Complete!"
echo "========================================="
echo ""
echo "Database location: $CEPHX_DB_PATH"
echo ""
echo "You can now test with the production key:"
echo "  export API_KEY='$PROD_KEY'"
echo "  curl -H \"X-API-Key: \$API_KEY\" http://localhost:8080/api/v1/auth/info"
echo ""
echo "Clean up demo database:"
echo "  rm -f $CEPHX_DB_PATH"
echo ""
