import os
import tempfile
from pathlib import Path

from biscotti.cli import _scan_for_agents, _init_config


class TestScanForAgents:
    def test_finds_basic_agent(self):
        """Finds Agent() assignments in files that import from pydantic_ai."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "agents").mkdir()
            (root / "agents" / "my_agent.py").write_text(
                "from pydantic_ai import Agent\n"
                "my_agent = Agent('openai:gpt-4o', instructions='Hello')\n"
            )
            agents = _scan_for_agents(root)
            assert len(agents) == 1
            assert agents[0][1] == "my_agent"

    def test_finds_multiple_agents(self):
        """Finds multiple Agent() assignments across files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.py").write_text(
                "from pydantic_ai import Agent\n"
                "agent_a = Agent('test')\n"
            )
            (root / "b.py").write_text(
                "from pydantic_ai import Agent\n"
                "agent_b = Agent('test')\n"
            )
            agents = _scan_for_agents(root)
            names = [a[1] for a in agents]
            assert "agent_a" in names
            assert "agent_b" in names

    def test_skips_venv(self):
        """Does not scan inside .venv or venv directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".venv" / "lib").mkdir(parents=True)
            (root / ".venv" / "lib" / "agent.py").write_text(
                "from pydantic_ai import Agent\n"
                "agent = Agent('test')\n"
            )
            agents = _scan_for_agents(root)
            assert len(agents) == 0

    def test_skips_hidden_dirs(self):
        """Does not scan inside hidden directories (starting with .)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".hidden").mkdir()
            (root / ".hidden" / "agent.py").write_text(
                "from pydantic_ai import Agent\n"
                "agent = Agent('test')\n"
            )
            agents = _scan_for_agents(root)
            assert len(agents) == 0

    def test_skips_node_modules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "node_modules" / "pkg" / "agent.py").write_text(
                "from pydantic_ai import Agent\n"
                "agent = Agent('test')\n"
            )
            agents = _scan_for_agents(root)
            assert len(agents) == 0

    def test_ignores_file_without_agent_import(self):
        """Files that don't import Agent from pydantic_ai are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "no_agent.py").write_text(
                "from pydantic_ai import Tool\n"
                "my_tool = Tool()\n"
            )
            agents = _scan_for_agents(root)
            assert len(agents) == 0

    def test_handles_syntax_errors_gracefully(self):
        """Files with syntax errors are skipped without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "bad.py").write_text("def broken(\n")
            (root / "good.py").write_text(
                "from pydantic_ai import Agent\n"
                "agent = Agent('test')\n"
            )
            agents = _scan_for_agents(root)
            assert len(agents) == 1
            assert agents[0][1] == "agent"


class TestInitConfig:
    def test_generates_config_file(self):
        """Generates biscotti_config.py with discovered agents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "app").mkdir()
            (root / "app" / "agent.py").write_text(
                "from pydantic_ai import Agent\n"
                "my_agent = Agent('openai:gpt-4o')\n"
            )
            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                _init_config()
                config = (root / "biscotti_config.py").read_text()
                assert "from biscotti.pydanticai import register" in config
                assert "my_agent" in config
            finally:
                os.chdir(old_cwd)

    def test_does_not_overwrite_without_force(self):
        """Existing config is not overwritten without --force."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "biscotti_config.py").write_text("# existing config\n")
            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                _init_config(force=False)
                config = (root / "biscotti_config.py").read_text()
                assert config == "# existing config\n"
            finally:
                os.chdir(old_cwd)

    def test_overwrites_with_force(self):
        """Existing config is overwritten with --force."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "biscotti_config.py").write_text("# old\n")
            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                _init_config(force=True)
                config = (root / "biscotti_config.py").read_text()
                assert "from biscotti.pydanticai import register" in config
            finally:
                os.chdir(old_cwd)

    def test_generates_placeholder_when_no_agents_found(self):
        """When no agents found, generates placeholder example."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_cwd = os.getcwd()
            try:
                os.chdir(root)
                _init_config()
                config = (root / "biscotti_config.py").read_text()
                assert "from biscotti.pydanticai import register" in config
                # Should have placeholder/example comments
                assert "register(" in config.lower() or "my_agent" in config.lower() or "no pydanticai" in config.lower()
            finally:
                os.chdir(old_cwd)
