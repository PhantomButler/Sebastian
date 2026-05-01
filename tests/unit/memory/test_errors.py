from __future__ import annotations

import pytest

from sebastian.memory.errors import (
    InvalidCandidateError,
    MemoryError,
    UnknownSlotError,
)
from sebastian.memory.writing.slots import DEFAULT_SLOT_REGISTRY


def test_unknown_slot_is_subclass_of_memory_error() -> None:
    assert issubclass(UnknownSlotError, MemoryError)
    assert issubclass(InvalidCandidateError, MemoryError)


def test_require_unknown_slot_raises_unknown_slot_error() -> None:
    with pytest.raises(UnknownSlotError):
        DEFAULT_SLOT_REGISTRY.require("no.such.slot")
