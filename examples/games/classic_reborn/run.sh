#!/bin/bash
# Run Classic Reborn Client
#
# Usage: ./run.sh [username] [password] [--server host] [--port port] [--version ver] [--no-gmap]
#
# Examples:
#   ./run.sh                    # Start with server browser
#   ./run.sh hosler 1234        # Auto-login to localhost with default version 2.1
#   ./run.sh hosler 1234 --server hastur.eevul.net --port 14912 --version 6.034
#   ./run.sh hosler 1234 --no-gmap  # Disable GMAP mode (use traditional level warping)
#
# Options:
#   --server host   # Server hostname (default: localhost)
#   --port port     # Server port (default: 14900)
#   --version ver   # Client version (default: 2.1)
#   --no-gmap       # Disable GMAP mode - treat all levels as individual
#
# Quick scripts:
#   ./run_local.sh   # Auto-login to localhost (no GMAP)
#   ./run_hastur.sh  # Auto-login to hastur (full GMAP support)

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Go to PyReborn root to ensure imports work
cd "$DIR/../../.."

# Run the client
python "$DIR/main.py" "$@"