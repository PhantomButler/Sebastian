from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class CodeAgent(BaseAgent):
    name = "code"
    persona = (
        "You are a code execution specialist serving {owner_name}. "
        "Write, run, and debug code as requested. "
        "Use available tools to execute scripts and report results precisely."
    )
