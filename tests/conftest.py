import pytest
from biscotti.registry import _REGISTRY
from biscotti.runner import _AGENT_CALLABLES
from biscotti.key_store import _KEYS


@pytest.fixture(autouse=True)
def _clean_global_state():
    """Snapshot and restore global state between tests."""
    reg_snapshot = dict(_REGISTRY)
    call_snapshot = dict(_AGENT_CALLABLES)
    keys_snapshot = dict(_KEYS)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(reg_snapshot)
    _AGENT_CALLABLES.clear()
    _AGENT_CALLABLES.update(call_snapshot)
    _KEYS.clear()
    _KEYS.update(keys_snapshot)
