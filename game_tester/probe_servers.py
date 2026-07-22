"""Command-line entry point for the passive server catalog probe."""

import argparse
import contextlib
import io
import json

from .server_probe import DEFAULT_CATALOG, parse_versions, probe_servers


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe public servers passively")
    parser.add_argument("--server")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--versions",
        help=("comma-separated client versions; each matrix row uses a fresh, "
              "pin-strict connection (no version retry), and a refusal records "
              "the server-advertised version"),
    )
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--wander", type=int, metavar="N")
    parser.add_argument("--deep", action="store_true",
                        help="crawl linked levels and record parser/render coverage")
    parser.add_argument("--max-levels", type=int, default=15, metavar="N")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()
    if args.wander is not None and args.wander < 0:
        parser.error("--wander must be non-negative")
    if args.max_levels < 0:
        parser.error("--max-levels must be non-negative")
    try:
        versions = parse_versions(args.versions)
    except ValueError as exc:
        parser.error(str(exc))
    if args.json_only:
        with (contextlib.redirect_stdout(io.StringIO()),
              contextlib.redirect_stderr(io.StringIO())):
            catalog = probe_servers(args.server, args.timeout, args.catalog, args.wander,
                                    deep=args.deep, max_levels=args.max_levels,
                                    versions=versions)
        print(json.dumps(catalog, sort_keys=True))
    else:
        catalog = probe_servers(args.server, args.timeout, args.catalog, args.wander,
                                deep=args.deep, max_levels=args.max_levels,
                                versions=versions)
        print(f"Catalogued {len(catalog['servers'])} server(s) in {args.catalog}")


if __name__ == "__main__":
    main()
