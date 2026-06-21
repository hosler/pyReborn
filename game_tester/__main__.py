"""
Game Tester CLI - Automated QA for pyReborn

Usage:
    python -m game_tester                    # Run all tests
    python -m game_tester --explore 60       # Explore for 60 seconds
    python -m game_tester --bots 3           # Run with 3 bots
    python -m game_tester --host 192.168.1.1 # Connect to specific host
    python -m game_tester --report report    # Save reports to report.json/html
"""

import sys
import argparse
import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from game_tester.game_bot import GameBot
from game_tester.bug_detector import BugDetector
from game_tester.multi_bot import MultiBotTest
from game_tester.test_scenarios import TestScenarios
from game_tester.reporter import TestReporter
from game_tester.explorer import ExplorerBot


def run_single_bot_tests(host: str, port: int, reporter: TestReporter) -> bool:
    """Run single-bot test scenarios."""
    print("\n[SINGLE BOT TESTS]")

    bot = GameBot("testbot1", host, port)

    if not bot.connect():
        print(f"  Failed to connect to {host}:{port}")
        return False

    try:
        # Run all scenarios
        results = TestScenarios.run_all_single_bot_tests(bot)

        for result in results:
            reporter.add_result(
                result.name,
                result.passed,
                result.duration,
                result.details,
                result.issues
            )
            reporter.print_result(result)

    finally:
        bot.disconnect()

    return True


def run_multi_bot_tests(host: str, port: int, num_bots: int,
                        reporter: TestReporter) -> bool:
    """Run multi-bot test scenarios."""
    print(f"\n[MULTI-BOT TESTS] ({num_bots} bots)")

    test = MultiBotTest(num_bots, host, port)

    if not test.connect_all():
        print(f"  Failed to connect all bots")
        return False

    try:
        results = test.run_all_multi_tests()

        for result in results:
            reporter.add_result(
                f"multi_{result.name}",
                result.passed,
                result.duration,
                result.details,
                result.issues
            )
            # Print result
            status = "\033[92m[✓]\033[0m" if result.passed else "\033[91m[✗]\033[0m"
            print(f"{status} {result.name.ljust(30)} {result.duration:.1f}s")
            if result.details:
                print(f"    {result.details}")

    finally:
        test.disconnect_all()

    return True


def run_explorer_mode(host: str, port: int, duration: float,
                      reporter: TestReporter) -> bool:
    """Run autonomous explorer mode."""
    print(f"\n[EXPLORER MODE] ({duration}s)")

    bot = GameBot("explorer", host, port)

    if not bot.connect():
        print(f"  Failed to connect to {host}:{port}")
        return False

    try:
        explorer = ExplorerBot(bot)
        result = explorer.explore(duration=duration, verbose=True)

        # Add explorer results to reporter
        reporter.add_result(
            "explorer_coverage",
            True,  # Informational
            result.duration,
            f"Visited {result.tiles_visited}/{result.total_tiles} tiles "
            f"({result.tiles_visited / result.total_tiles * 100:.1f}%)",
            []
        )

        reporter.add_result(
            "explorer_actions",
            True,  # Informational
            result.duration,
            f"Performed {result.actions_performed} actions",
            []
        )

        reporter.add_result(
            "explorer_anomalies",
            result.anomalies_detected == 0,
            result.duration,
            f"Detected {result.anomalies_detected} anomalies",
            result.issues
        )

        # Print coverage map
        print("\n")
        explorer.print_coverage_map()

        # Print anomalies found
        if result.issues:
            print("\n[ANOMALIES FOUND]")
            for issue in result.issues:
                color = "\033[91m" if issue.severity == "HIGH" else "\033[93m"
                print(f"  {color}[{issue.severity}]\033[0m {issue.description}")

    finally:
        bot.disconnect()

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Game Tester - Automated QA for pyReborn",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m game_tester                    # Run all tests
    python -m game_tester --explore 60       # Explore for 60 seconds
    python -m game_tester --bots 3           # Run with 3 bots
    python -m game_tester --single           # Run single-bot tests only
    python -m game_tester --multi            # Run multi-bot tests only
    python -m game_tester --report report    # Save reports
        """
    )

    parser.add_argument("--host", default="localhost",
                       help="Server hostname (default: localhost)")
    parser.add_argument("--port", type=int, default=14900,
                       help="Server port (default: 14900)")
    parser.add_argument("--bots", type=int, default=2,
                       help="Number of bots for multi-bot tests (default: 2)")
    parser.add_argument("--single", action="store_true",
                       help="Run only single-bot tests")
    parser.add_argument("--multi", action="store_true",
                       help="Run only multi-bot tests")
    parser.add_argument("--explore", type=float, default=None,
                       help="Run explorer AI for N seconds (e.g., --explore 60)")
    parser.add_argument("--coverage", action="store_true",
                       help="Run the packet-coverage harness (needs GS_PKTLOG server)")
    parser.add_argument("--coverage-rc", action="store_true",
                       help="Run the RC admin packet-coverage harness")
    parser.add_argument("--coverage-nc", action="store_true",
                       help="Run the NC (npc-control) packet-coverage harness")
    parser.add_argument("--gmap", action="store_true",
                       help="Run the GMAP world test suite (needs gmaps=chicken.gmap)")
    parser.add_argument("--report", type=str, default=None,
                       help="Base filename for reports (e.g., 'report' -> report.json, report.html)")

    args = parser.parse_args()

    # GMAP suite runs standalone (own bot lifecycle + account-reset teardown).
    if args.gmap:
        from game_tester.gmap_tests import run_gmap_tests
        print("\n[GMAP TESTS]")
        reporter = TestReporter("Game Tester - GMAP")
        reporter.set_config(host=f"{args.host}:{args.port}", bots=2, mode="gmap")
        gresults = run_gmap_tests(host=args.host, port=args.port)
        for r in gresults:
            reporter.add_result(r.name, r.passed, r.duration, r.details, r.issues)
            reporter.print_result(r)
        reporter.print_summary()
        if args.report:
            reporter.save_json(f"{args.report}_gmap.json")
        sys.exit(0 if all(r.passed for r in gresults) else 1)

    # Coverage mode runs standalone (own bot lifecycle, own report format).
    if args.coverage or args.coverage_rc or args.coverage_nc:
        from game_tester.packet_coverage import (
            run_coverage, run_coverage_rc, run_coverage_nc)
        if args.coverage_nc:
            runner, suffix = run_coverage_nc, "_coverage_nc"
        elif args.coverage_rc:
            runner, suffix = run_coverage_rc, "_coverage_rc"
        else:
            runner, suffix = run_coverage, "_coverage"
        report = runner(host=args.host, port=args.port)
        report.print_summary()
        if args.report:
            import json
            with open(f"{args.report}{suffix}.json", "w") as f:
                json.dump(report.to_dict(), f, indent=2)
            print(f"  wrote {args.report}{suffix}.json")
        sys.exit(0 if not report.gaps() else 1)

    # Determine mode
    if args.explore:
        mode = "explore"
    elif args.single:
        mode = "single"
    elif args.multi:
        mode = "multi"
    else:
        mode = "all"

    # Create reporter
    reporter = TestReporter("Game Tester - pyReborn QA")
    reporter.set_config(
        host=f"{args.host}:{args.port}",
        bots=args.bots,
        mode=mode,
        explore_duration=args.explore if args.explore else 0
    )

    reporter.print_header()

    success = True

    # Run explorer mode
    if args.explore:
        if not run_explorer_mode(args.host, args.port, args.explore, reporter):
            success = False
    else:
        # Run standard tests
        if not args.multi:
            if not run_single_bot_tests(args.host, args.port, reporter):
                success = False

        if not args.single and args.bots >= 2:
            if not run_multi_bot_tests(args.host, args.port, args.bots, reporter):
                success = False

    # Print summary
    reporter.print_summary()

    # Save reports
    if args.report:
        reporter.save_json(f"{args.report}.json")
        reporter.save_html(f"{args.report}.html")

    # Exit with appropriate code
    sys.exit(0 if not reporter.has_failures() else 1)


if __name__ == "__main__":
    main()
