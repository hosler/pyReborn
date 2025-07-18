#!/bin/bash
# Run Classic Reborn Client
#
# Usage: ./run.sh [username] [password] [--server host] [--port port] [--version ver]
#
# Examples:
#   ./run.sh                    # Start with server browser
#   ./run.sh hosler 1234        # Auto-login to localhost with default version 2.1
#   ./run.sh hosler 1234 --server hastur.eevul.net --port 14912 --version 6.034
#
# Quick scripts:
#   ./run_local.sh   # Auto-login to localhost (no GMAP)
#   ./run_hastur.sh  # Auto-login to hastur (full GMAP support)

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Go to PyReborn root to ensure imports work
cd "$DIR/../../.."

# Run the client
python "$DIR/classic_reborn_client.py" "$@"