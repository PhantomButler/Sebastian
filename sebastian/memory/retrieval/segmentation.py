from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _jieba() -> Any:
    """Lazily import jieba, raising a clear error if not installed."""
    try:
        import jieba  # type: ignore[import-untyped]

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


def build_match_query(terms: list[str]) -> str:
    """Wrap each term as a double-quoted phrase for FTS5 MATCH.

    Prevents operators (AND/OR/NOT/*/quote/paren) inside the user query from
    being interpreted as FTS5 syntax. Inner double-quote characters are escaped
    by doubling them (FTS5 convention). Empty term list yields an empty-string
    phrase, which FTS5 treats as no-match.
    """
    safe = [f'"{t.replace(chr(34), chr(34) * 2)}"' for t in terms if t]
    return " ".join(safe) if safe else '""'
