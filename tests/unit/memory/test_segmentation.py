from __future__ import annotations

from sebastian.memory.retrieval.segmentation import (
    add_entity_terms,
    build_match_query,
    segment_for_fts,
    terms_for_query,
)


def test_segment_for_fts_chinese_contains_expected_words() -> None:
    result = segment_for_fts("用户偏好简洁中文回复")
    tokens = result.split()
    assert "用户" in tokens
    assert "偏好" in tokens
    assert "中文" in tokens


def test_terms_for_query_filters_single_char() -> None:
    result = terms_for_query("用户偏好")
    # All returned tokens must have len > 1
    assert all(len(t) > 1 for t in result)
    # Expected multi-char tokens should be present
    assert "用户" in result or "偏好" in result


def test_add_entity_terms_makes_names_recognized() -> None:
    add_entity_terms(["小橘", "ForgeAgent"])
    result_cn = segment_for_fts("小橘很聪明")
    result_en = segment_for_fts("ForgeAgent is running")
    assert "小橘" in result_cn.split()
    assert "ForgeAgent" in result_en.split()


def test_english_tokens_preserved() -> None:
    result = segment_for_fts("LLM")
    assert "LLM" in result.split()


def test_segment_for_fts_english_phrase_preserved() -> None:
    result = segment_for_fts("Memory Artifact")
    tokens = result.split()
    assert "Memory" in tokens
    assert "Artifact" in tokens


def test_terms_for_query_returns_list() -> None:
    result = terms_for_query("用户偏好")
    assert isinstance(result, list)


def test_segment_for_fts_returns_nonempty_string_for_nonempty_input() -> None:
    result = segment_for_fts("你好世界")
    assert isinstance(result, str)
    assert len(result.strip()) > 0


def test_build_match_query_single_term() -> None:
    assert build_match_query(["项目"]) == '"项目"'


def test_build_match_query_multiple_terms() -> None:
    result = build_match_query(["记忆", "模块"])
    assert result == '"记忆" "模块"'


def test_build_match_query_empty() -> None:
    assert build_match_query([]) == '""'


def test_build_match_query_escapes_double_quotes() -> None:
    result = build_match_query(['say "hello"'])
    assert '""' in result  # inner quote is doubled
