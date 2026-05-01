from __future__ import annotations

import importlib


MOVED_MEMORY_MODULES = [
    "sebastian.memory.stores.profile_store",
    "sebastian.memory.stores.episode_store",
    "sebastian.memory.stores.entity_registry",
    "sebastian.memory.stores.slot_definition_store",
    "sebastian.memory.writing.pipeline",
    "sebastian.memory.writing.resolver",
    "sebastian.memory.writing.write_router",
    "sebastian.memory.writing.decision_log",
    "sebastian.memory.writing.feedback",
    "sebastian.memory.writing.slot_proposals",
    "sebastian.memory.writing.slots",
    "sebastian.memory.retrieval.retrieval",
    "sebastian.memory.retrieval.retrieval_lexicon",
    "sebastian.memory.retrieval.depth_guard",
    "sebastian.memory.retrieval.segmentation",
    "sebastian.memory.consolidation.consolidation",
    "sebastian.memory.consolidation.extraction",
    "sebastian.memory.consolidation.prompts",
    "sebastian.memory.consolidation.provider_bindings",
    "sebastian.memory.resident.resident_snapshot",
    "sebastian.memory.resident.resident_dedupe",
]

KEY_EXTERNAL_ENTRYPOINTS = [
    "sebastian.core.base_agent",
    "sebastian.gateway.app",
    "sebastian.capabilities.tools.memory_save",
    "sebastian.capabilities.tools.memory_search",
]


def test_memory_reorganized_modules_are_importable() -> None:
    for module_name in MOVED_MEMORY_MODULES:
        importlib.import_module(module_name)


def test_memory_external_entrypoints_are_importable() -> None:
    for module_name in KEY_EXTERNAL_ENTRYPOINTS:
        importlib.import_module(module_name)
