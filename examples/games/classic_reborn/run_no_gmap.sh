#!/bin/bash
# Run Classic Reborn Client with GMAP mode disabled
#
# This demonstrates traditional level-based navigation where:
# - Each level is independent
# - Edge warps use level links
# - No seamless GMAP transitions
#
# Usage: ./run_no_gmap.sh [username] [password]

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Default to localhost if no args
if [ $# -lt 2 ]; then
    echo "Usage: $0 <username> <password>"
    echo "Example: $0 hosler 1234"
    exit 1
fi

USERNAME=$1
PASSWORD=$2

echo "Starting Classic Reborn Client with GMAP mode DISABLED"
echo "This uses traditional level warping instead of seamless GMAP transitions"
echo ""

# Run with --no-gmap flag
"$DIR/run.sh" "$USERNAME" "$PASSWORD" --no-gmap