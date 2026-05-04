from __future__ import annotations

import importlib
import logging
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sebastian.permissions.types import ALL_TOOLS, AllToolsSentinel

if TYPE_CHECKING:
    from sebastian.core.base_agent import BaseAgent


# 每个子代理无论 capability 白名单如何，都必须具备的协议工具。
# 这些工具决定子代理在层级中的通信能力，不属于领域能力范畴，
# 不应该要求每个 manifest 手动声明。
# 注意：Sebastian 不经过 _loader.py，因此不受此影响。
_SUBAGENT_PROTOCOL_TOOLS: tuple[str, ...] = (
    "ask_parent",  # 向上级请示，暂停等待回复
    "resume_agent",  # 恢复等待中的下属执行（ask_parent 的对称操作）
    "stop_agent",  # 停止指定下属代理
    "spawn_sub_agent",  # 向下分派 depth=3 组员
    "check_sub_agents",  # 查看自己的组员任务状态
    "inspect_session",  # 查看指定 session 的详细进展
)


@dataclass
class AgentConfig:
    agent_type: str
    name: str  # agent class name (e.g. "ForgeAgent")
    description: str
    max_children: int  # max concurrent depth=3 sessions
    stalled_threshold_minutes: int  # stalled detection threshold in minutes
    agent_class: type[BaseAgent]
    allowed_tools: list[str] | AllToolsSentinel | None = None
    allowed_skills: list[str] | None = None


def load_agents(extra_dirs: list[Path] | None = None) -> list[AgentConfig]:
    """Scan built-in agents dir and optional extra dirs for manifest.toml files.

    Builtins are always scanned first. extra_dirs are appended after, so a later
    entry with the same agent_type will override an earlier one (including builtins).
    """
    builtin_dir = Path(__file__).parent
    dirs: list[tuple[Path, bool]] = [(builtin_dir, True)]
    if extra_dirs:
        dirs += [(d, False) for d in extra_dirs]

    configs: dict[str, AgentConfig] = {}

    for base_dir, is_builtin in dirs:
        if not base_dir.exists():
            continue
        for entry in sorted(base_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            manifest_path = entry / "manifest.toml"
            if not manifest_path.exists():
                continue

            with manifest_path.open("rb") as f:
                data = tomllib.load(f)

            agent_section = data.get("agent", data)
            agent_type = entry.name
            class_name: str = agent_section.get("class_name", "")

            if is_builtin:
                module_path = f"sebastian.agents.{agent_type}"
            else:
                if str(base_dir) not in sys.path:
                    sys.path.insert(0, str(base_dir))
                module_path = agent_type

            try:
                mod = importlib.import_module(module_path)
                agent_class = getattr(mod, class_name)
            except (ImportError, AttributeError) as exc:
                logging.getLogger(__name__).warning("Failed to load agent %r: %s", agent_type, exc)
                continue

            # allowed_tools / allowed_skills: missing tools mean protocol-only.
            raw_tools = agent_section.get("allowed_tools")
            raw_skills = agent_section.get("allowed_skills")

            if raw_tools == "ALL":
                effective_tools: list[str] | AllToolsSentinel = ALL_TOOLS
            elif isinstance(raw_tools, str):
                raise ValueError(f"{manifest_path}: allowed_tools string must be 'ALL'")
            else:
                capability_tools = list(raw_tools or [])
                protocol_extra = [t for t in _SUBAGENT_PROTOCOL_TOOLS if t not in capability_tools]
                effective_tools = capability_tools + protocol_extra

            configs[agent_type] = AgentConfig(
                agent_type=agent_type,
                name=agent_section.get("class_name", agent_type),
                description=agent_section.get("description", ""),
                max_children=int(agent_section.get("max_children", 5)),
                stalled_threshold_minutes=int(agent_section.get("stalled_threshold_minutes", 5)),
                agent_class=agent_class,
                allowed_tools=effective_tools,
                allowed_skills=list(raw_skills) if raw_skills is not None else None,
            )

    return list(configs.values())
