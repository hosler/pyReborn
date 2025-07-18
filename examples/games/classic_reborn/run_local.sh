#!/bin/bash
# Auto-login script for local server (basic testing)
#
# Usage: ./run_local.sh [username] [password]
# Default: hosler / 1234

USERNAME=${1:-hosler}
PASSWORD=${2:-1234}

echo "Connecting to localhost:14900 with version 2.1"
echo "Username: $USERNAME"
echo "Note: This server has basic levels, NPCs, items but NO GMAP support"
echo ""

python3 classic_reborn_client.py "$USERNAME" "$PASSWORD" \
    --server localhost \
    --port 14900 \
    --version 2.1