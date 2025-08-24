#!/bin/bash
# Run script for Reborn Modern client
cd /home/hosler/Projects/opengraal2/pyReborn/examples/games/reborn_modern
# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Add PyReborn to Python path
export PYTHONPATH="${SCRIPT_DIR}/../../..:${PYTHONPATH}"

# Run the game with any provided arguments
python3 "${SCRIPT_DIR}/main.py" "$@"