#!/bin/bash
# Run Classic Reborn Client with v2 architecture
#
# Usage: ./run_v2.sh [username] [password] [--server host] [--port port] [--version ver]
#
# This script runs the client with PyReborn v2 architecture enabled

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Go to PyReborn root to ensure imports work
cd "$DIR/../../.."

# Run the client with v2 flag
python "$DIR/classic_reborn_client.py" "$@" --v2