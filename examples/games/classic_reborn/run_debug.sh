#!/bin/bash
# Run Classic Reborn with debug logging for GMAP rendering

cd "$(dirname "$0")"

# Set environment variables for debug logging
export PYTHONUNBUFFERED=1
export PYGAME_HIDE_SUPPORT_PROMPT=1

# Create a debug log config
cat > debug_logging.py << EOF
import logging

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('gmap_debug.log', mode='w')
    ]
)

# Set specific module levels
logging.getLogger('pyreborn.managers.level_manager').setLevel(logging.INFO)
logging.getLogger('pyreborn.core.client').setLevel(logging.INFO) 
logging.getLogger('game.client').setLevel(logging.DEBUG)
logging.getLogger('managers.gmap').setLevel(logging.DEBUG)
logging.getLogger('core.renderer').setLevel(logging.INFO)
logging.getLogger('parsers.gmap_preloader').setLevel(logging.INFO)

# Reduce noise
logging.getLogger('pyreborn.protocol').setLevel(logging.WARNING)
logging.getLogger('pyreborn.packets').setLevel(logging.WARNING)
logging.getLogger('pygame').setLevel(logging.WARNING)
EOF

# Run with debug logging and auto-connect to hastur
python -c "
import debug_logging
import sys
sys.path.insert(0, '.')
from main import main
sys.argv = ['main.py', 'hosler', '1234', '--server', 'hastur.eevul.net', '--port', '14912', '--version', '6.034']
main()
"