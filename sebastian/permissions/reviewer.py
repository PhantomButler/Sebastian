# sebastian/permissions/reviewer.py
from __future__ import annotations

import json
import logging
from typing import Any

from sebastian.permissions.types import ReviewDecision

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a security reviewer for an AI assistant system.
Your job: decide whether a tool call should proceed directly or require user approval.

Rules:
- PROCEED if: the action is reversible, read-only, or clearly aligned with the stated task goal
- ESCALATE if: the action is destructive, irreversible, accesses sensitive data,
  or the stated reason does not match the task goal
- When in doubt, ESCALATE

Respond ONLY in valid JSON:
{"decision": "proceed" | "escalate", "explanation": "..."}
explanation must be in the user's language, written for a non-technical user.
When decision is "proceed", explanation is an empty string.\
"""


class PermissionReviewer:
    """Stateless LLM reviewer for MODEL_DECIDES tool calls.

    Each review is a single API call with no session state.
    Defaults to escalate on any failure (conservative).
    """

    def __init__(self, client: Any, model: str = "claude-haiku-4-5-20251001") -> None:
        self._client = client
        self._model = model

    async def review(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        task_goal: str,
    ) -> ReviewDecision:
        """Return a proceed/escalate decision for the given tool call."""
        user_content = (
            f"Task goal: {task_goal}\n"
            f"Tool: {tool_name}\n"
            f"Input: {json.dumps(tool_input, ensure_ascii=False)}\n"
            f"Model's reason: {reason}"
        )
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=256,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = message.content[0].text.strip()
            data = json.loads(raw)
            decision = data.get("decision", "escalate")
            if decision not in ("proceed", "escalate"):
                decision = "escalate"
            explanation = data.get("explanation", "")
            return ReviewDecision(decision=decision, explanation=explanation)
        except Exception:
            logger.exception("PermissionReviewer failed, defaulting to escalate")
            return ReviewDecision(
                decision="escalate",
                explanation="Permission review failed; manual approval required.",
            )
