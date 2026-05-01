from __future__ import annotations

# Memory component binding keys — must not overlap with any agent type registered in agent_registry.
# Convention: agent types use agent name (e.g., "coder"), memory components use "memory_" prefix.
MEMORY_EXTRACTOR_BINDING = "memory_extractor"
MEMORY_CONSOLIDATOR_BINDING = "memory_consolidator"

MEMORY_COMPONENT_TYPES: frozenset[str] = frozenset(
    {
        MEMORY_EXTRACTOR_BINDING,
        MEMORY_CONSOLIDATOR_BINDING,
    }
)

MEMORY_COMPONENT_META: dict[str, dict[str, str]] = {
    MEMORY_EXTRACTOR_BINDING: {
        "display_name": "记忆提取器",
        "description": "从会话片段中提取候选 memory artifact",
    },
    MEMORY_CONSOLIDATOR_BINDING: {
        "display_name": "记忆沉淀器",
        "description": "会话结束后归纳 session summary 和推断偏好",
    },
}
