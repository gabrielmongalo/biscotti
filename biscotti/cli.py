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

    init_cmd = sub.add_parser("init-claude", help="Set up Claude Code skill for biscotti integration")
    init_cmd.add_argument("--force", action="store_true", help="Overwrite existing skill file")

    args = parser.parse_args()

    if args.command == "dev":
        _run_dev(host=args.host, port=args.port)
    elif args.command == "init-claude":
        _init_claude(force=args.force)
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


def _init_claude(force: bool = False) -> None:
    from pathlib import Path
    import importlib.resources

    dest_dir = Path(".claude/commands")
    dest_file = dest_dir / "biscotti.md"

    if dest_file.exists() and not force:
        print(f"  {dest_file} already exists.")
        print("  Use --force to overwrite.")
        return

    # Read the bundled template
    template = importlib.resources.files("biscotti").joinpath("_skill_template.md").read_text()

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file.write_text(template)

    print()
    print("  biscotti Claude Code skill installed")
    print()
    print(f"  Written to: {dest_file}")
    print()
    print("  Claude Code now knows how to:")
    print("  - Add biscotti to your existing agents")
    print("  - Write test cases for your prompts")
    print("  - Debug common integration issues")
    print()


if __name__ == "__main__":
    main()
