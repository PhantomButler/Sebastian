from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, get_type_hints

from sebastian.core.types import ToolResult

logger = logging.getLogger(__name__)

ToolFn = Callable[..., Awaitable[ToolResult]]

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class ToolSpec:
    """Specification and metadata for a registered tool."""

    __slots__ = ("name", "description", "parameters", "requires_approval", "permission_level")

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        requires_approval: bool = False,
        permission_level: str = "owner",
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.requires_approval = requires_approval
        self.permission_level = permission_level


# Module-level registry: tool name → (spec, async callable)
_tools: dict[str, tuple[ToolSpec, ToolFn]] = {}


def _infer_json_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Infer JSON schema from function signature."""
    sig = inspect.signature(fn)
    # Use get_type_hints to resolve string annotations from "from __future__ import annotations"
    try:
        # Include builtins and common types in localns
        hints = get_type_hints(
            fn,
            localns={
                "int": int,
                "str": str,
                "float": float,
                "bool": bool,
                "ToolResult": ToolResult,
            },
        )
    except Exception as e:
        logger.debug(
            "get_type_hints failed for %s: %s, falling back to raw annotations",
            fn.__name__,
            e,
        )
        # Fall back to raw annotations if hints cannot be resolved
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in sig.parameters.items():
        # Prefer resolved type hint over raw annotation
        ann = hints.get(param_name, param.annotation)
        json_type = _TYPE_MAP.get(ann, "string")
        properties[param_name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    return {"type": "object", "properties": properties, "required": required}


def tool(
    name: str,
    description: str,
    requires_approval: bool = False,
    permission_level: str = "owner",
) -> Callable[[ToolFn], ToolFn]:
    """Decorator that registers an async function as a callable tool."""

    def decorator(fn: ToolFn) -> ToolFn:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=_infer_json_schema(fn),
            requires_approval=requires_approval,
            permission_level=permission_level,
        )

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
            return await fn(*args, **kwargs)

        _tools[name] = (spec, wrapper)
        logger.debug("Tool registered: %s", name)
        return wrapper

    return decorator


def get_tool(name: str) -> tuple[ToolSpec, ToolFn] | None:
    """Retrieve a registered tool by name."""
    return _tools.get(name)


def list_tool_specs() -> list[ToolSpec]:
    """List all registered tool specifications."""
    return [spec for spec, _ in _tools.values()]


async def call_tool(name: str, **kwargs: Any) -> ToolResult:
    """Execute a tool by name with the given arguments."""
    entry = _tools.get(name)
    if entry is None:
        return ToolResult(ok=False, error=f"Tool not found: {name}")
    _, fn = entry
    return await fn(**kwargs)
