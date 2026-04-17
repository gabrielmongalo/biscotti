"""
biscotti.cli
~~~~~~~~~~~~
Command-line interface.

    biscotti dev          -> spin up the demo app with two example agents
    biscotti dev --port   -> pick a port
    biscotti init         -> generate biscotti_config.py for your project
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


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

    init_proj = sub.add_parser("init", help="Generate biscotti_config.py for your project")
    init_proj.add_argument("--force", action="store_true", help="Overwrite existing config")

    args = parser.parse_args()

    if args.command == "dev":
        _run_dev(host=args.host, port=args.port)
    elif args.command == "init-claude":
        _init_claude(force=args.force)
    elif args.command == "init":
        _init_config(force=args.force)
    else:
        parser.print_help()


def _run_dev(host: str, port: int) -> None:
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required to run the dev server.")
        print("  pip install uvicorn")
        sys.exit(1)

    config_path = Path("biscotti_config.py")

    if config_path.exists():
        # User project mode — import config to trigger register() calls
        _import_user_config(config_path)
        _print_banner(host, port, demo=False)
        uvicorn.run(
            "biscotti._user_source:app",
            host=host,
            port=port,
            reload=False,
            log_level="warning",
        )
    else:
        # Demo mode
        _print_banner(host, port, demo=True)
        uvicorn.run(
            "biscotti._demo_source:app",
            host=host,
            port=port,
            reload=False,
            log_level="warning",
        )


def _import_user_config(config_path: Path) -> None:
    """Import biscotti_config.py to trigger register() calls."""
    import importlib.util

    # Add CWD to sys.path so the user's imports resolve
    cwd = str(config_path.parent.resolve())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    spec = importlib.util.spec_from_file_location("biscotti_config", config_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


def _print_banner(host: str, port: int, demo: bool = True) -> None:
    url = f"http://{host}:{port}/biscotti"
    print()
    print("  biscotti dev server")
    print()
    print(f"  UI   ->  {url}")
    print(f"  API  ->  {url}/api/agents")
    print()
    if demo:
        print("  Mode: demo (no biscotti_config.py found)")
        print("  Run `biscotti init` to connect your agents.")
    else:
        from .registry import list_agents
        agents = list_agents()
        print(f"  Mode: project ({len(agents)} agent(s) registered)")
        for a in agents:
            print(f"    - {a.name}")
    print()
    print("  Press Ctrl+C to stop.")
    print()


def _init_claude(force: bool = False) -> None:
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


def _scan_for_agents(root: Path) -> list[tuple[str, str]]:
    """Scan Python files under *root* for PydanticAI Agent instances.

    Returns a list of ``(relative_file_path, variable_name)`` tuples for every
    module-level ``Agent(...)`` assignment found in files that import ``Agent``
    from ``pydantic_ai``.
    """
    skip_dirs = {".venv", "venv", "node_modules", "__pycache__"}
    results: list[tuple[str, str]] = []

    for py_file in sorted(root.rglob("*.py")):
        # Skip hidden directories, explicitly skipped dirs, and biscotti dirs
        parts = py_file.relative_to(root).parts
        if any(
            p.startswith(".") or p in skip_dirs or "biscotti" in p
            for p in parts[:-1]  # check directory parts, not the filename
        ):
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        # Check whether the file imports Agent from pydantic_ai
        imports_agent = False
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "pydantic_ai" in node.module:
                    for alias in node.names:
                        if alias.name == "Agent":
                            imports_agent = True
                            break
            if imports_agent:
                break

        if not imports_agent:
            continue

        # Find module-level assignments whose value is an Agent() call
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.Assign):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            is_agent_call = (
                (isinstance(func, ast.Name) and func.id == "Agent")
                or (
                    isinstance(func, ast.Attribute)
                    and func.attr == "Agent"
                )
            )
            if not is_agent_call:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    rel = str(py_file.relative_to(root))
                    results.append((rel, target.id))

    return results


def _init_config(force: bool = False) -> None:
    """Generate a ``biscotti_config.py`` from discovered PydanticAI agents."""
    config_path = Path("biscotti_config.py")

    if config_path.exists() and not force:
        print(f"  {config_path} already exists.")
        print("  Use --force to overwrite.")
        return

    agents = _scan_for_agents(Path("."))

    lines: list[str] = [
        '"""',
        "biscotti_config.py",
        "~~~~~~~~~~~~~~~~~~",
        "Generated by `biscotti init`. Uncomment agents to register.",
        '"""',
        "from biscotti.pydanticai import register",
        "",
    ]

    if agents:
        for filepath, varname in agents:
            # Convert file path to module path: app/agents/file.py -> app.agents.file
            module = filepath.replace("/", ".").replace("\\", ".")
            if module.endswith(".py"):
                module = module[:-3]

            # Derive slug: remove _agent suffix, replace _ with -
            slug = varname
            if slug.endswith("_agent"):
                slug = slug[: -len("_agent")]
            slug = slug.replace("_", "-")

            lines.append(f"# from {module} import {varname}")
            lines.append(f'# register({varname}, name="{slug}")')
            lines.append("")
    else:
        lines.append("# No PydanticAI agents found. Add your agents below:")
        lines.append("#")
        lines.append("# from my_app.agents import my_agent")
        lines.append('# register(my_agent, name="my-agent")')
        lines.append("")

    config_path.write_text("\n".join(lines), encoding="utf-8")

    count = len(agents)
    print()
    print("  biscotti config generated")
    print()
    print(f"  Written to: {config_path}")
    if agents:
        print(f"  Found {count} agent(s) — uncomment the ones you want.")
    else:
        print("  No agents found — add them manually to the config.")
    print()
    print("  Next: edit biscotti_config.py, then run `biscotti dev`")
    print()


if __name__ == "__main__":
    main()
