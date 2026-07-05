#!/usr/bin/env bash
# One-shot LLM playtest: spin up a throwaway server + daemon, turn a fleet of
# persona agents loose to play the game and find bugs, write a report, tear down.
# Needs ANTHROPIC_API_KEY (or `rbw get anthropic-api-key`). See
# game_tester/playtest_run.py for options.
set -euo pipefail
cd "$(dirname "$0")"
exec python3.13 -m game_tester.playtest_run "$@"
