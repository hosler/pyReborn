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
    parser.add_argument("--tier1", action="store_true",
                       help="Run the board-modify/large-file protocol-parity suite")
    parser.add_argument("--tier2", action="store_true",
                       help="Run the entity-family (bomb/arrow/horse/flagdel) protocol-parity suite")
    parser.add_argument("--tier3", action="store_true",
                       help="Run the server-control (freeze/say2/triggeraction/serverwarp) suite")
    parser.add_argument("--tier5", action="store_true",
                       help="Run the GS2 bytecode transport (weapon/class/gani) suite")
    parser.add_argument("--gs2", action="store_true",
                       help="Run the GS2 VM execution suite (weapon lifecycle, "
                            "timeout loop, class join, triggeraction round-trip, corpus)")
    parser.add_argument("--gs1", action="store_true",
                       help="Run the GS1 behavioral conformance suite: same GS1 "
                            "NPC scripts on pygserver vs the C++ gs2emu oracle, "
                            "diffing client-observable effects")
    parser.add_argument("--behaviour", "--fingerprint", action="store_true",
                       dest="behaviour",
                       help="Run the live behavioural-fingerprint suite: log in "
                            "with a real GameClient, then assert the SHAPE of "
                            "what the server's scripts built (GUI tree, weapon "
                            "VMs, events fired, host calls) against the "
                            "checked-in baseline. Catches a script silently "
                            "taking the wrong branch, which no other suite can.")
    parser.add_argument("--behaviour-server", metavar="NAME", default=None,
                       help="Fingerprint only this baseline entry (e.g. 'Login')")
    parser.add_argument("--behaviour-seconds", type=float, default=None,
                       metavar="SECONDS",
                       help="Override the per-server observation window")
    parser.add_argument("--rebaseline", action="store_true",
                       help="With --behaviour: rewrite the baselines from this "
                            "run instead of checking against them (deliberate "
                            "re-baseline after a real server-content change)")
    parser.add_argument("--rebaseline-pins", action="store_true",
                       help="With --rebaseline: also reset the hand-curated "
                            "required/forbidden sets (they are preserved by "
                            "default, since they encode outage knowledge)")
    parser.add_argument("--report", type=str, default=None,
                       help="Base filename for reports (e.g., 'report' -> report.json, report.html)")
    catalog_group = parser.add_mutually_exclusive_group()
    catalog_group.add_argument("--catalog-server", metavar="NAME",
                               help="Run the catalogued test subset for one server")
    catalog_group.add_argument("--catalog-all", action="store_true",
                               help="Run catalogued test subsets for every server")
    parser.add_argument("--no-fingerprint", action="store_true",
                       help="With --catalog-*: skip the behavioural fingerprint "
                            "of catalogued servers that have a baseline")

    args = parser.parse_args()

    # Behaviour fingerprints run standalone (own client lifecycle, own
    # baseline file).
    if args.behaviour:
        from game_tester.behaviour_fingerprint import run_behaviour_checks
        print("\n[BEHAVIOUR FINGERPRINTS]")
        explicit_address = ("--host" in sys.argv) or ("--port" in sys.argv)
        ok = run_behaviour_checks(
            args.behaviour_server,
            rebaseline=args.rebaseline,
            reset_pins=args.rebaseline_pins,
            host=args.host if explicit_address else None,
            port=args.port if explicit_address else None,
            seconds=args.behaviour_seconds,
        )
        sys.exit(0 if ok else 1)

    if args.catalog_server or args.catalog_all:
        from game_tester.server_probe import run_catalog_tests
        ok = run_catalog_tests(args.catalog_server,
                               fingerprint=not args.no_fingerprint)
        sys.exit(0 if ok else 1)

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

    # Tier1 suite runs standalone (own bot lifecycle).
    if args.tier1:
        from game_tester.tier1_tests import run_tier1_tests
        print("\n[TIER1 TESTS]")
        reporter = TestReporter("Game Tester - Tier1")
        reporter.set_config(host=f"{args.host}:{args.port}", bots=2, mode="tier1")
        tresults = run_tier1_tests(host=args.host, port=args.port)
        for r in tresults:
            reporter.add_result(r.name, r.passed, r.duration, r.details, r.issues)
            reporter.print_result(r)
        reporter.print_summary()
        if args.report:
            reporter.save_json(f"{args.report}_tier1.json")
        sys.exit(0 if all(r.passed for r in tresults) else 1)

    # Tier2 suite runs standalone (own bot lifecycle).
    if args.tier2:
        from game_tester.tier2_tests import run_tier2_tests
        print("\n[TIER2 TESTS]")
        reporter = TestReporter("Game Tester - Tier2")
        reporter.set_config(host=f"{args.host}:{args.port}", bots=2, mode="tier2")
        tresults = run_tier2_tests(host=args.host, port=args.port)
        for r in tresults:
            reporter.add_result(r.name, r.passed, r.duration, r.details, r.issues)
            reporter.print_result(r)
        reporter.print_summary()
        if args.report:
            reporter.save_json(f"{args.report}_tier2.json")
        sys.exit(0 if all(r.passed for r in tresults) else 1)

    # Tier5 suite runs standalone (own bot lifecycle).
    if args.tier5:
        from game_tester.tier5_tests import run_tier5_tests
        print("\n[TIER5 TESTS]")
        reporter = TestReporter("Game Tester - Tier5")
        reporter.set_config(host=f"{args.host}:{args.port}", bots=1, mode="tier5")
        tresults = run_tier5_tests(host=args.host, port=args.port)
        for r in tresults:
            reporter.add_result(r.name, r.passed, r.duration, r.details, r.issues)
            reporter.print_result(r)
        reporter.print_summary()
        if args.report:
            reporter.save_json(f"{args.report}_tier5.json")
        sys.exit(0 if all(r.passed for r in tresults) else 1)

    # GS2 VM suite runs standalone (own bot lifecycle).
    if args.gs2:
        from game_tester.gs2_tests import run_gs2_tests
        print("\n[GS2 VM TESTS]")
        reporter = TestReporter("Game Tester - GS2 VM")
        reporter.set_config(host=f"{args.host}:{args.port}", bots=2, mode="gs2")
        tresults = run_gs2_tests(host=args.host, port=args.port)
        for r in tresults:
            reporter.add_result(r.name, r.passed, r.duration, r.details, r.issues)
            reporter.print_result(r)
        reporter.print_summary()
        if args.report:
            reporter.save_json(f"{args.report}_gs2.json")
        sys.exit(0 if all(r.passed for r in tresults) else 1)

    # GS1 conformance suite runs standalone (spawns its own servers, or
    # captures from a single --host/--port target).
    if args.gs1:
        from game_tester.gs1_conformance import run_gs1_conformance
        print("\n[GS1 CONFORMANCE TESTS]")
        reporter = TestReporter("Game Tester - GS1 Conformance")
        reporter.set_config(host=f"{args.host}:{args.port}", bots=1, mode="gs1")
        # An explicit host/port means "capture that one server"; the bare
        # --gs1 spawns pygserver + gs2emu itself and diffs.
        explicit = ("--host" in sys.argv) or ("--port" in sys.argv)
        tresults = run_gs1_conformance(
            host=args.host, port=args.port, explicit_target=explicit)
        for r in tresults:
            reporter.add_result(r.name, r.passed, r.duration, r.details, r.issues)
            reporter.print_result(r)
        reporter.print_summary()
        if args.report:
            reporter.save_json(f"{args.report}_gs1.json")
        sys.exit(0 if all(r.passed for r in tresults) else 1)

    # Tier3 suite runs standalone (own bot lifecycle).
    if args.tier3:
        from game_tester.tier3_tests import run_tier3_tests
        print("\n[TIER3 TESTS]")
        reporter = TestReporter("Game Tester - Tier3")
        reporter.set_config(host=f"{args.host}:{args.port}", bots=2, mode="tier3")
        tresults = run_tier3_tests(host=args.host, port=args.port)
        for r in tresults:
            reporter.add_result(r.name, r.passed, r.duration, r.details, r.issues)
            reporter.print_result(r)
        reporter.print_summary()
        if args.report:
            reporter.save_json(f"{args.report}_tier3.json")
        sys.exit(0 if all(r.passed for r in tresults) else 1)

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
