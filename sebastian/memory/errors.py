from __future__ import annotations


class MemoryError(Exception):
    """Base class for all memory subsystem errors."""


class UnknownSlotError(MemoryError):
    """Raised when a slot_id is referenced but not registered."""


class InvalidCandidateError(MemoryError):
    """Raised when a CandidateArtifact fails normalization/validation."""


class DecisionLogPersistenceError(MemoryError):
    """Raised when decision_log append fails at persistence layer."""
