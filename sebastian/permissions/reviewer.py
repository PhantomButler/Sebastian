from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sebastian.permissions.types import ReviewDecision

if TYPE_CHECKING:
    from sebastian.llm.registry import LLMProviderRegistry

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

    Holds a reference to the LLM registry and lazily resolves the default
    provider on each review() call. This way the reviewer can be constructed
    before any provider is configured — at review time, if the registry still
    has no provider, the reviewer falls back to a safe escalate decision.
    """

    def __init__(self, llm_registry: LLMProviderRegistry) -> None:
        self._llm_registry = llm_registry

    async def review(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        reason: str,
        task_goal: str,
    ) -> ReviewDecision:
        """Return a proceed/escalate decision for the given tool call."""
        from sebastian.core.stream_events import TextDelta

        try:
            provider, model = await self._llm_registry.get_default_with_model()
        except RuntimeError:
            logger.warning(
                "PermissionReviewer: no LLM provider configured, defaulting to escalate"
            )
            return ReviewDecision(
                decision="escalate",
                explanation="未配置 LLM Provider，无法自动审查工具调用，请人工批准。",
            )

        user_content = (
            f"Task goal: {task_goal}\n"
            f"Tool: {tool_name}\n"
            f"Input: {json.dumps(tool_input, ensure_ascii=False)}\n"
            f"Model's reason: {reason}"
        )
        try:
            text = ""
            async for event in provider.stream(
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
                tools=[],
                model=model,
                max_tokens=256,
            ):
                if isinstance(event, TextDelta):
                    text += event.delta
            data = json.loads(text.strip())
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
