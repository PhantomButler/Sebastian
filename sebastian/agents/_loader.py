from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sebastian.core.base_agent import BaseAgent


@dataclass
class AgentConfig:
    agent_type: str
    name: str
    description: str
    worker_count: int
    agent_class: type[BaseAgent]
    allowed_tools: list[str] | None = None
    allowed_skills: list[str] | None = None


def load_agents(extra_dirs: list[Path] | None = None) -> list[AgentConfig]:
    """Scan built-in agents dir and optional extra dirs for manifest.toml files.

    When extra_dirs is provided, only those directories are scanned (builtin is skipped).
    This allows tests and user extensions to load agents in isolation.
    When extra_dirs is None, the built-in agents directory is scanned.
    """
    if extra_dirs is not None:
        dirs: list[tuple[Path, bool]] = [(d, False) for d in extra_dirs]
    else:
        builtin_dir = Path(__file__).parent
        dirs = [(builtin_dir, True)]

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
                import sys

                if str(base_dir) not in sys.path:
                    sys.path.insert(0, str(base_dir))
                module_path = agent_type

            try:
                mod = importlib.import_module(module_path)
                agent_class = getattr(mod, class_name)
            except (ImportError, AttributeError) as exc:
                import logging

                logging.getLogger(__name__).warning("Failed to load agent %r: %s", agent_type, exc)
                continue

            # allowed_tools / allowed_skills: None if not declared, list if declared
            raw_tools = agent_section.get("allowed_tools")
            raw_skills = agent_section.get("allowed_skills")

            configs[agent_type] = AgentConfig(
                agent_type=agent_type,
                name=agent_section.get("name", agent_type),
                description=agent_section.get("description", ""),
                worker_count=int(agent_section.get("worker_count", 3)),
                agent_class=agent_class,
                allowed_tools=list(raw_tools) if raw_tools is not None else None,
                allowed_skills=list(raw_skills) if raw_skills is not None else None,
            )

    return list(configs.values())
