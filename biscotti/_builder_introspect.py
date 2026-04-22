"""
biscotti._builder_introspect
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
AST-based introspection of user-prompt builder functions.

A "builder" is a Python function that takes a ``dict`` (typically fetched
from a DB) and returns a string — the user prompt to send to an LLM.
Example::

    def _build_wine_prompt(wine_info, include_vintage_context=False):
        name     = wine_info.get("wine", "Unknown")
        vintage  = wine_info.get("vintage", "")
        producer = wine_info.get("producer", "Unknown")
        return f"\"\"\"Write a portrait for this wine.
        Wine: {name}
        Vintage: {vintage}
        Producer: {producer}
        \"\"\""

``introspect_builder(fn)`` analyzes the function and returns::

    {
        "variables": ["wine", "vintage", "producer"],
        "defaults":  {"wine": "Unknown", "vintage": "", "producer": "Unknown"},
        "template":  "Write a portrait for this wine.\\nWine: {{wine}}\\n..."
    }

Three-tier fallback:
  A. AST rewrite (best quality — walks JoinedStr/FormattedValue nodes,
     substitutes {{key}} for each local mapped to a dict key).
  B. Render-and-replace (runs the function with a placeholder dict, then
     string-replaces the placeholders with {{key}}).
  C. Keys-only (flat template listing each detected variable on its own line).
"""
from __future__ import annotations

import ast
import inspect
from typing import Any, Callable


class UnsupportedPattern(Exception):
    """Raised internally when AST rewrite can't handle a construct."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def introspect_builder(
    fn: Callable[..., str],
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract variables, defaults, and a {{var}} template from a builder fn.

    Parameters
    ----------
    fn:
        An async or sync function that takes a dict (positional arg 0) plus
        optional extra kwargs, and returns a string.
    extras:
        Extra kwargs to pass to the builder during Approach B's render pass.
        Used for builders like ``_build_wine_prompt(wine_info,
        include_vintage_context=True)`` where a non-dict arg changes the
        template shape.

    Returns
    -------
    dict
        ``{"variables": [...], "defaults": {...}, "template": "..."}``.
        If source for ``fn`` cannot be retrieved (e.g. defined inline in a
        ``python -c`` or ``exec``), returns empty lists with a minimal
        placeholder template.
    """
    extras = extras or {}

    try:
        variables, defaults = _extract_keys_and_defaults(fn)
    except (OSError, UnsupportedPattern):
        # Source not available (inline defs, exec, lambdas) — nothing to extract
        return {
            "variables": [],
            "defaults": {},
            "template": f"[biscotti] Could not introspect {fn.__name__} — edit this template in the UI.",
        }

    # Signature fallback for builders that use typed positional args (no
    # dict-access pattern). Tried when the AST walker finds nothing.
    if not variables:
        sig_vars, sig_defaults = _signature_fallback(fn, extras)
        if sig_vars:
            template = "\n".join(f"{v}: {{{{{v}}}}}" for v in sig_vars)
            return {"variables": sig_vars, "defaults": sig_defaults, "template": template}

    try:
        template = _ast_rewrite(fn, variables, extras)
        return {"variables": variables, "defaults": defaults, "template": template}
    except UnsupportedPattern:
        pass

    try:
        template = _render_and_replace(fn, variables, extras)
        return {"variables": variables, "defaults": defaults, "template": template}
    except Exception:
        pass

    # Approach C — keys-only flat template
    template = "\n".join(f"{v}: {{{{{v}}}}}" for v in variables)
    return {"variables": variables, "defaults": defaults, "template": template}


def _signature_fallback(
    fn: Callable, extras: dict[str, Any]
) -> tuple[list[str], dict[str, str]]:
    """Extract variables from a function's signature.

    Used when the AST walker finds no ``dict.get()``/``dict[key]`` patterns —
    common for builders that take typed positional args instead of a dict::

        def format_wine_notes(
            wine_name: str,
            vintage: int | None,
            wine_type: str | None = None,
        ) -> str:
            ...

    Returns parameter names as variables, param defaults (or ``""``) as
    defaults. Excludes ``*args``, ``**kwargs``, and any param whose name
    appears in ``extras`` (those are bind-time overrides, not user inputs).
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return [], {}

    variables: list[str] = []
    defaults: dict[str, str] = {}
    for name, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if name in extras:
            continue
        variables.append(name)
        if param.default is not inspect.Parameter.empty and param.default is not None:
            defaults[name] = str(param.default)
        else:
            defaults[name] = ""
    return variables, defaults


# ---------------------------------------------------------------------------
# Keys + defaults extraction (common to all approaches)
# ---------------------------------------------------------------------------

def _parse_fn(fn: Callable) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Parse a function's source into an AST, tolerating nested-function indent.

    ``textwrap.dedent`` fails on functions that contain multi-line string
    literals whose content sits at column 0 (because dedent considers those
    lines when computing the common indent). Instead, strip the def-line's
    indent only from lines that actually have it — leaving triple-string
    content untouched.
    """
    source = inspect.getsource(fn)
    lines = source.splitlines(keepends=True)
    first_nonblank = next((l for l in lines if l.strip()), None)
    if first_nonblank is None:
        raise UnsupportedPattern("Empty source")

    indent = len(first_nonblank) - len(first_nonblank.lstrip())
    if indent > 0:
        prefix = " " * indent
        lines = [l[indent:] if l.startswith(prefix) else l for l in lines]
        source = "".join(lines)

    tree = ast.parse(source)
    node = tree.body[0]
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise UnsupportedPattern(f"Not a function: {type(node).__name__}")
    return node


def _extract_keys_and_defaults(fn: Callable) -> tuple[list[str], dict[str, str]]:
    """Walk the function body for every dict-access pattern.

    Recognizes:
      - ``x = arg.get("k", default)``  → key="k", default=default
      - ``x = arg.get("k")``           → key="k", default=""
      - ``x = arg["k"]``               → key="k", default=""

    Also detects inline usage inside f-strings and expressions:
      - ``f"...{info.get('k', 'D')}..."``
      - ``f"...{info['k']}..."``
    """
    fn_node = _parse_fn(fn)
    variables: list[str] = []
    defaults: dict[str, str] = {}

    def _record(key: str | None, default: str | None) -> None:
        if key is None:
            return
        if key not in variables:
            variables.append(key)
        if default is not None and key not in defaults:
            defaults[key] = default

    for node in ast.walk(fn_node):
        # Pattern 1: Assign — local = info.get("k", "d") or info["k"]
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name):
                key, default = _extract_key_from_value(node.value)
                _record(key, default)
                continue

        # Pattern 2: inline Call — info.get("k", "d")
        if isinstance(node, ast.Call):
            key, default = _extract_key_from_value(node)
            _record(key, default)
            continue

        # Pattern 3: inline Subscript — info["k"]
        if isinstance(node, ast.Subscript):
            key, default = _extract_key_from_value(node)
            _record(key, default)
            continue

    return variables, defaults


def _extract_key_from_value(value: ast.expr) -> tuple[str | None, str | None]:
    """Given the RHS of an Assign, try to extract (dict_key, default_value).

    Returns (None, None) if the value isn't a recognized dict access.
    """
    # Pattern: arg.get("k") or arg.get("k", default)
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "get"
        and value.args
        and isinstance(value.args[0], ast.Constant)
        and isinstance(value.args[0].value, str)
    ):
        key = value.args[0].value
        default = ""
        if len(value.args) > 1 and isinstance(value.args[1], ast.Constant):
            default = str(value.args[1].value) if value.args[1].value is not None else ""
        return key, default

    # Pattern: arg["k"]
    if (
        isinstance(value, ast.Subscript)
        and isinstance(value.slice, ast.Constant)
        and isinstance(value.slice.value, str)
    ):
        return value.slice.value, ""

    return None, None


# ---------------------------------------------------------------------------
# Approach A — AST rewrite
# ---------------------------------------------------------------------------

def _ast_rewrite(
    fn: Callable, variables: list[str], extras: dict[str, Any]
) -> str:
    """Walk the function body statically and rewrite f-strings as {{var}} templates.

    Builds a map of local-var → dict-key, then walks the return statement's
    JoinedStr nodes. Each FormattedValue that references a mapped local gets
    rewritten to ``{{key}}``. Conditional IfExp assignments pick the truthy
    branch.
    """
    fn_node = _parse_fn(fn)
    local_to_key: dict[str, str] = {}
    local_to_exprstr: dict[str, str] = {}  # for IfExp/complex locals

    for node in ast.walk(fn_node):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if not isinstance(tgt, ast.Name):
                continue
            local_name = tgt.id

            # Direct dict access → map to key
            key, _ = _extract_key_from_value(node.value)
            if key is not None:
                local_to_key[local_name] = key
                continue

            # Conditional (IfExp) → resolve to truthy branch's rendered string
            if isinstance(node.value, ast.IfExp):
                truthy = _render_expr(node.value.body, local_to_key)
                if truthy is not None:
                    local_to_exprstr[local_name] = truthy
                    continue

    # Find the return expression
    ret_expr = _find_return(fn_node)
    if ret_expr is None:
        raise UnsupportedPattern("No return expression found")

    rendered = _render_expr(ret_expr, local_to_key, local_to_exprstr)
    if rendered is None:
        raise UnsupportedPattern("Could not render return expression")
    return rendered


def _find_return(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.expr | None:
    """Find the single top-level return statement's value expression."""
    for stmt in fn_node.body:
        if isinstance(stmt, ast.Return) and stmt.value is not None:
            return stmt.value
    return None


def _render_expr(
    expr: ast.expr,
    local_to_key: dict[str, str],
    local_to_exprstr: dict[str, str] | None = None,
) -> str | None:
    """Render an AST expression as a template string.

    Supported node types:
      - Constant(str)        → literal text
      - JoinedStr            → concatenate values (literal + FormattedValue)
      - FormattedValue       → lookup the inner Name in local_to_key
      - Name                 → lookup in local_to_key or local_to_exprstr
    Returns None if a child node isn't renderable.
    """
    local_to_exprstr = local_to_exprstr or {}

    if isinstance(expr, ast.Constant):
        if isinstance(expr.value, str):
            return expr.value
        return str(expr.value)

    if isinstance(expr, ast.JoinedStr):
        out: list[str] = []
        for part in expr.values:
            rendered = _render_expr(part, local_to_key, local_to_exprstr)
            if rendered is None:
                return None
            out.append(rendered)
        return "".join(out)

    if isinstance(expr, ast.FormattedValue):
        # The inner value references a local or expression; format_spec is ignored
        inner = expr.value
        return _render_expr(inner, local_to_key, local_to_exprstr)

    if isinstance(expr, ast.Name):
        if expr.id in local_to_key:
            return "{{" + local_to_key[expr.id] + "}}"
        if expr.id in local_to_exprstr:
            return local_to_exprstr[expr.id]
        return None  # unknown reference — bail to fallback

    if isinstance(expr, ast.IfExp):
        # Emit the truthy branch's rendering
        return _render_expr(expr.body, local_to_key, local_to_exprstr)

    # Direct dict access inline: f"{info.get('k')}"
    if isinstance(expr, (ast.Call, ast.Subscript)):
        key, _ = _extract_key_from_value(expr)
        if key is not None:
            return "{{" + key + "}}"

    return None


# ---------------------------------------------------------------------------
# Approach B — render with placeholder dict, then string-replace
# ---------------------------------------------------------------------------

_PLACEHOLDER_PREFIX = "__BIS_"
_PLACEHOLDER_SUFFIX = "__"


def _render_and_replace(
    fn: Callable, variables: list[str], extras: dict[str, Any]
) -> str:
    """Call the function with a placeholder dict and substitute back to {{var}}.

    Works on builders that:
      - take a dict as the first positional arg
      - return a str synchronously (no await)
    """
    if inspect.iscoroutinefunction(fn):
        raise UnsupportedPattern("Async builders not supported in render mode")

    placeholder_dict = {
        k: f"{_PLACEHOLDER_PREFIX}{k}{_PLACEHOLDER_SUFFIX}" for k in variables
    }

    # Include any extra kwargs so the function can find them. For extras that
    # aren't known variables, we also pass them through as-is.
    call_kwargs = dict(extras)
    rendered = fn(placeholder_dict, **call_kwargs)
    if not isinstance(rendered, str):
        raise UnsupportedPattern(f"Builder returned {type(rendered).__name__}, expected str")

    template = rendered
    for key in variables:
        placeholder = f"{_PLACEHOLDER_PREFIX}{key}{_PLACEHOLDER_SUFFIX}"
        template = template.replace(placeholder, "{{" + key + "}}")

    # Also surface extras as {{var}} if they're referenced in the output
    for extra_key, extra_val in extras.items():
        if isinstance(extra_val, str) and extra_val in template:
            template = template.replace(extra_val, "{{" + extra_key + "}}")

    return template
