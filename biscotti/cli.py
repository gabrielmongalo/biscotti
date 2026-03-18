"""
biscotti.cli
~~~~~~~~~~~~
Command-line interface.

    biscotti dev          -> spin up the demo app with two example agents
    biscotti dev --port   -> pick a port
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="biscotti",
        description="biscotti — prompt playground for AI agents",
    )
    sub = parser.add_subparsers(dest="command")

    dev_cmd = sub.add_parser("dev", help="Run a local demo with example agents")
    dev_cmd.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    dev_cmd.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")

    args = parser.parse_args()

    if args.command == "dev":
        _run_dev(host=args.host, port=args.port)
    else:
        parser.print_help()


def _run_dev(host: str, port: int) -> None:
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required to run the dev server.")
        print("  pip install uvicorn")
        sys.exit(1)

    _print_banner(host, port)

    uvicorn.run(
        "biscotti._demo_source:app",
        host=host,
        port=port,
        reload=False,
        log_level="warning",   # keep output clean
    )


def _print_banner(host: str, port: int) -> None:
    url = f"http://{host}:{port}/biscotti"
    print()
    print("  biscotti dev server")
    print()
    print(f"  UI   ->  {url}")
    print(f"  API  ->  {url}/api/agents")
    print()
    print("  Two demo agents are pre-loaded.")
    print("  Edit their prompts, run tests, save versions.")
    print()
    print("  Press Ctrl+C to stop.")
    print()


if __name__ == "__main__":
    main()
