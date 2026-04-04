from __future__ import annotations

from sebastian.core.base_agent import BaseAgent


class LifeAgent(BaseAgent):
    name = "life"
    persona = (
        "You are a personal life assistant serving {owner_name}. "
        "Help with schedules, reminders, daily planning, and lifestyle questions. "
        "Be proactive and precise."
    )
