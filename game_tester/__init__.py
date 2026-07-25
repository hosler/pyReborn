"""
Game Tester - Automated QA framework for pyReborn

Usage:
    python -m game_tester              # Run all tests
    python -m game_tester --explore    # Run explorer AI mode
    python -m game_tester --bots 3     # Run with 3 bots
"""

from .game_bot import GameBot
from .bug_detector import BugDetector
from .multi_bot import MultiBotTest
from .reporter import TestReporter
from .explorer import ExplorerBot
from .screenshots import ScreenshotCapture
from .packet_coverage import run_coverage, run_coverage_rc, CoverageReport, PacketTrace
from .exercise import run_exercise_battery
from .exercise_rc import run_rc_battery
from .behaviour_fingerprint import (capture_from_client, capture_target,
                                    compare as compare_fingerprint,
                                    run_behaviour_checks)

__all__ = ['GameBot', 'BugDetector', 'MultiBotTest', 'TestReporter', 'ExplorerBot',
           'ScreenshotCapture', 'run_coverage', 'run_coverage_rc', 'CoverageReport',
           'PacketTrace', 'run_exercise_battery', 'run_rc_battery',
           'run_behaviour_checks', 'capture_target', 'capture_from_client',
           'compare_fingerprint']
__version__ = '0.1.0'
