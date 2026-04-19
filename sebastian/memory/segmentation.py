from __future__ import annotations

from typing import Iterable


def _jieba():
    """Lazily import jieba, raising a clear error if not installed."""
    try:
        import jieba
        return jieba
    except ImportError:
        raise RuntimeError(
            "jieba is required for memory FTS segmentation. Install sebastian[memory]."
        )


def add_entity_terms(terms: Iterable[str]) -> None:
    """Add custom terms to jieba's user dictionary for better entity segmentation."""
    jb = _jieba()
    for term in terms:
        jb.add_word(term)


def segment_for_fts(text: str) -> str:
    """Segment text for FTS5 indexing. Returns space-separated tokens."""
    jb = _jieba()
    tokens = jb.cut_for_search(text)
    return " ".join(t for t in tokens if t)


def terms_for_query(query: str) -> list[str]:
    """Segment a search query. Returns tokens with len > 1 only."""
    jb = _jieba()
    tokens = jb.cut_for_search(query)
    return [t for t in (tok.strip() for tok in tokens) if t and len(t) > 1]
