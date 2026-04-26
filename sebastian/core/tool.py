# sebastian/core/tool.py
from __future__ import annotations

import functools
import inspect
import json
import logging
import types
from collections.abc import Awaitable, Callable
from typing import Any, Union, get_args, get_origin, get_type_hints

from sebastian.core.types import ToolResult
from sebastian.permissions.types import PermissionTier

logger = logging.getLogger(__name__)

ToolFn = Callable[..., Awaitable[ToolResult]]

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}

_NoneType = type(None)


class ToolSpec:
    """Specification and metadata for a registered tool."""

    __slots__ = ("name", "description", "parameters", "permission_tier")

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        permission_tier: PermissionTier = PermissionTier.LOW,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.permission_tier = permission_tier


# Module-level registry: tool name → (spec, async callable)
_tools: dict[str, tuple[ToolSpec, ToolFn]] = {}


def _unwrap_optional(hint: Any) -> Any:
    """X | None → X。非 Optional 类型原样返回。"""
    origin = get_origin(hint)
    # Handle both typing.Union and types.UnionType (for Python 3.10+ | syntax)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(hint) if a is not _NoneType]
        if len(args) == 1:
            return args[0]
    return hint


def _type_to_json_schema(ann: Any) -> dict[str, Any]:
    """Convert a single Python type annotation to a JSON Schema dict."""
    origin = get_origin(ann)
    if origin is list:
        args = get_args(ann)
        item_schema = _type_to_json_schema(args[0]) if args else {}
        return {"type": "array", "items": item_schema}
    if origin is dict or ann is dict:
        return {"type": "object"}
    return {"type": _TYPE_MAP.get(ann, "string")}


def _infer_json_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Infer JSON schema from function signature."""
    sig = inspect.signature(fn)
    try:
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
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in sig.parameters.items():
        if param_name == "_ctx":  # framework-injected, not exposed to LLM
            continue
        ann = hints.get(param_name, param.annotation)
        effective_ann = _unwrap_optional(ann)
        properties[param_name] = _type_to_json_schema(effective_ann)
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    return {"type": "object", "properties": properties, "required": required}


def _coerce_args(fn: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    根据函数签名的类型注解对传入参数做宽松类型转换。
    将字符串 "2" → int 2，"3.14" → float 3.14，"true"/"1"/"yes" → bool True。
    转换失败时保留原值。支持 X | None（Optional）类型。
    """
    try:
        hints = get_type_hints(
            inspect.unwrap(fn),
            localns={
                "int": int,
                "str": str,
                "float": float,
                "bool": bool,
                "ToolResult": ToolResult,
            },
        )
    except Exception:
        return kwargs

    result = dict(kwargs)
    for name, value in kwargs.items():
        if not isinstance(value, str):
            continue
        hint = hints.get(name)
        if hint is None:
            continue
        target = _unwrap_optional(hint)
        if target is int:
            try:
                result[name] = int(value)
            except (ValueError, TypeError):
                pass
        elif target is float:
            try:
                result[name] = float(value)
            except (ValueError, TypeError):
                pass
        elif target is bool:
            result[name] = value.lower() in ("true", "1", "yes")
        elif get_origin(target) is list or get_origin(target) is dict:
            try:
                parsed = json.loads(value)
                expected = list if get_origin(target) is list else dict
                if isinstance(parsed, expected):
                    result[name] = parsed
            except (ValueError, TypeError):
                pass
    return result


def tool(
    name: str,
    description: str,
    permission_tier: PermissionTier = PermissionTier.MODEL_DECIDES,
) -> Callable[[ToolFn], ToolFn]:
    """Decorator that registers an async function as a callable tool."""

    def decorator(fn: ToolFn) -> ToolFn:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=_infer_json_schema(fn),
            permission_tier=permission_tier,
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
    coerced = _coerce_args(fn, kwargs)
    return await fn(**coerced)
