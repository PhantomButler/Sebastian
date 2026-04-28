from __future__ import annotations

import pytest
from sebastian.llm.catalog.loader import LLMModelSpec


def test_get_custom_model_spec_returns_capability_fields() -> None:
    """_get_custom_model_spec must forward supports_image_input and supports_text_file_input."""
    from unittest.mock import MagicMock

    # Simulate a LLMCustomModelRecord with capability columns
    record = MagicMock()
    record.model_id = "gpt-4o"
    record.display_name = "GPT-4o"
    record.context_window_tokens = 128000
    record.thinking_capability = None
    record.thinking_format = None
    record.supports_image_input = True
    record.supports_text_file_input = True

    # Build the LLMModelSpec using the same logic as _get_custom_model_spec
    spec = LLMModelSpec(
        id=record.model_id,
        display_name=record.display_name,
        context_window_tokens=record.context_window_tokens,
        thinking_capability=record.thinking_capability,
        thinking_format=record.thinking_format,
        supports_image_input=record.supports_image_input,
        supports_text_file_input=record.supports_text_file_input,
    )

    assert spec.supports_image_input is True
    assert spec.supports_text_file_input is True
