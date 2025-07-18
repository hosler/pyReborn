#!/bin/bash
# Auto-login script for hastur server (GMAP testing)
#
# Usage: ./run_hastur.sh [username] [password]
# Default: hosler / 1234

USERNAME=${1:-hosler}
PASSWORD=${2:-1234}

echo "Connecting to hastur.eevul.net:14912 with version 6.034"
echo "Username: $USERNAME"
echo "Note: This server has full GMAP support (Zelda: A Link to the Past)"
echo ""

python3 classic_reborn_client.py "$USERNAME" "$PASSWORD" \
    --server hastur.eevul.net \
    --port 14912 \
    --version 6.034