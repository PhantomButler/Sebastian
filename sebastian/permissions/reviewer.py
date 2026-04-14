# sebastian/permissions/reviewer.py
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from sebastian.config import settings
from sebastian.core.stream_events import TextDelta
from sebastian.permissions.types import ReviewDecision

if TYPE_CHECKING:
    from sebastian.llm.registry import LLMProviderRegistry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """\
You are a security reviewer for an AI assistant system.
Your job: decide whether a tool call should proceed directly or require user approval.

## General Rules

- PROCEED if the action is read-only, reversible, or clearly aligned with the stated task goal.
- ESCALATE if the action is destructive, irreversible, touches sensitive data, \
or the stated reason does not match the task goal.
- When in doubt, ESCALATE.

## Bash-Specific Rules

The static layer has already blocked the most obvious dangerous commands (rm, dd, mkfs, etc.).
You are reviewing commands that passed that layer. Still ESCALATE for:

- Any command that writes, modifies, moves, or deletes files \
outside the workspace directory (`{workspace_dir}`).
- Commands that install or uninstall system packages \
(apt, brew, pip install --system, npm install -g, etc.).
- Commands that modify system configuration \
(/etc/*, crontab, sysctl, network settings, firewall rules, etc.).
- Commands that create, modify, or delete users/groups \
(useradd, usermod, passwd, sudo visudo, etc.).
- Commands that access or exfiltrate sensitive paths \
(~/.ssh, ~/.gnupg, ~/.aws, /etc/shadow, /etc/passwd, etc.).
- Commands that open or expose network ports \
(nc -l, socat, python -m http.server on non-loopback interfaces, etc.).
- Commands that modify or disable security mechanisms \
(chmod 777 recursively, setenforce 0, ufw disable, etc.).
- Commands that download and execute arbitrary remote content \
(curl/wget piped to interpreter, eval with remote input, etc.).
- Any use of sudo or su to escalate privileges.

## Output Format

Respond ONLY in valid JSON:
{{"decision": "proceed" | "escalate", "explanation": "..."}}
- explanation must be in the user's language, written for a non-technical user.
- When decision is "proceed", explanation is an empty string.\
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
        try:
            provider, model = await self._llm_registry.get_default_with_model()
        except RuntimeError:
            logger.warning("PermissionReviewer: no LLM provider configured, defaulting to escalate")
            return ReviewDecision(
                decision="escalate",
                explanation="未配置 LLM Provider，无法自动审查工具调用，请人工批准。",
            )

        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(workspace_dir=settings.workspace_dir)

        user_content = (
            f"Task goal: {task_goal}\n"
            f"Tool: {tool_name}\n"
            f"Input: {json.dumps(tool_input, ensure_ascii=False)}\n"
            f"Model's reason: {reason}"
        )
        try:
            text = ""
            async for event in provider.stream(
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                tools=[],
                model=model,
                max_tokens=2048,
            ):
                if isinstance(event, TextDelta):
                    text += event.delta
            if not text.strip():
                logger.warning(
                    "PermissionReviewer: LLM returned empty response, defaulting to escalate"
                )
                return ReviewDecision(
                    decision="escalate",
                    explanation="审查响应为空，请人工批准。",
                )
            logger.info("PermissionReviewer raw response: %r", text)
            data = json.loads(_extract_json(text))
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


def _extract_json(text: str) -> str:
    """Extract JSON object from text, stripping markdown code fences if present."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        return text[start:end]
    return text.strip()
