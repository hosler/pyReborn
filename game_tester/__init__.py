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

__all__ = ['GameBot', 'BugDetector', 'MultiBotTest', 'TestReporter', 'ExplorerBot',
           'ScreenshotCapture', 'run_coverage', 'run_coverage_rc', 'CoverageReport',
           'PacketTrace', 'run_exercise_battery', 'run_rc_battery']
__version__ = '0.1.0'
