from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from sebastian.llm.catalog import (
    CatalogValidationError,
    LLMCatalog,
    load_builtin_catalog,
    load_catalog_from_path,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_model(**overrides: object) -> dict:
    base: dict = {
        "id": "test-model",
        "display_name": "Test Model",
        "context_window_tokens": 128_000,
        "thinking_capability": None,
        "thinking_format": None,
    }
    base.update(overrides)
    return base


def _minimal_provider(models: list[dict] | None = None, **overrides: object) -> dict:
    base: dict = {
        "id": "test-provider",
        "display_name": "Test Provider",
        "provider_type": "openai",
        "base_url": "https://api.example.com",
        "models": models if models is not None else [_minimal_model()],
    }
    base.update(overrides)
    return base


def _make_catalog(providers: list[dict] | None = None, **overrides: object) -> dict:
    payload: dict = {"version": 1}
    if providers is not None:
        payload["providers"] = providers
    else:
        payload["providers"] = [_minimal_provider()]
    payload.update(overrides)
    return payload


def _write_catalog(tmp_path: Path, payload: dict) -> Path:
    """Write *payload* as JSON inside *tmp_path* and return the file path."""
    p = tmp_path / "catalog.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ===================================================================
# TDD RED — write failing tests first
# ===================================================================


class TestLoadCatalogFromPath:
    """Tests for load_catalog_from_path()."""

    def test_happy_path_loads_valid_catalog(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, _make_catalog())
        catalog = load_catalog_from_path(path)

        assert isinstance(catalog, LLMCatalog)
        assert catalog.version == 1
        assert len(catalog.providers) == 1
        assert catalog.providers[0].id == "test-provider"

    def test_provider_lookup_by_id(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, _make_catalog())
        catalog = load_catalog_from_path(path)

        provider = catalog.get_provider("test-provider")
        assert provider.display_name == "Test Provider"

    def test_model_lookup_within_provider(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, _make_catalog())
        catalog = load_catalog_from_path(path)

        model = catalog.get_model("test-provider", "test-model")
        assert model.display_name == "Test Model"
        assert model.context_window_tokens == 128_000

    def test_get_provider_raises_keyerror_for_unknown(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, _make_catalog())
        catalog = load_catalog_from_path(path)

        with pytest.raises(KeyError):
            catalog.get_provider("nonexistent")

    def test_get_model_raises_keyerror_for_unknown_model(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, _make_catalog())
        catalog = load_catalog_from_path(path)

        with pytest.raises(KeyError):
            catalog.get_model("test-provider", "nonexistent-model")

    def test_file_not_found_raises_error(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_catalog_from_path(tmp_path / "nope.json")

    def test_invalid_json_raises_validation_error(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(CatalogValidationError):
            load_catalog_from_path(p)


class TestValidation:
    """Validation rules raise CatalogValidationError."""

    def test_duplicate_provider_ids(self, tmp_path: Path) -> None:
        dup_providers = [_minimal_provider(), _minimal_provider()]
        path = _write_catalog(tmp_path, _make_catalog(providers=dup_providers))
        with pytest.raises(CatalogValidationError, match="[Dd]uplicate provider"):
            load_catalog_from_path(path)

    def test_duplicate_model_ids_within_provider(self, tmp_path: Path) -> None:
        provider = _minimal_provider(models=[_minimal_model(), _minimal_model()])
        path = _write_catalog(tmp_path, _make_catalog(providers=[provider]))
        with pytest.raises(CatalogValidationError, match="[Dd]uplicate model"):
            load_catalog_from_path(path)

    def test_invalid_provider_type(self, tmp_path: Path) -> None:
        provider = _minimal_provider(provider_type="gemini")
        path = _write_catalog(tmp_path, _make_catalog(providers=[provider]))
        with pytest.raises(CatalogValidationError, match="provider_type"):
            load_catalog_from_path(path)

    def test_invalid_thinking_capability(self, tmp_path: Path) -> None:
        provider = _minimal_provider(models=[_minimal_model(thinking_capability="telepathy")])
        path = _write_catalog(tmp_path, _make_catalog(providers=[provider]))
        with pytest.raises(CatalogValidationError, match="thinking_capability"):
            load_catalog_from_path(path)

    def test_invalid_thinking_format(self, tmp_path: Path) -> None:
        provider = _minimal_provider(models=[_minimal_model(thinking_format="brain_waves")])
        path = _write_catalog(tmp_path, _make_catalog(providers=[provider]))
        with pytest.raises(CatalogValidationError, match="thinking_format"):
            load_catalog_from_path(path)

    def test_context_window_too_small(self, tmp_path: Path) -> None:
        provider = _minimal_provider(models=[_minimal_model(context_window_tokens=100)])
        path = _write_catalog(tmp_path, _make_catalog(providers=[provider]))
        with pytest.raises(CatalogValidationError, match="context_window"):
            load_catalog_from_path(path)

    def test_context_window_too_large(self, tmp_path: Path) -> None:
        provider = _minimal_provider(models=[_minimal_model(context_window_tokens=20_000_000)])
        path = _write_catalog(tmp_path, _make_catalog(providers=[provider]))
        with pytest.raises(CatalogValidationError, match="context_window"):
            load_catalog_from_path(path)

    def test_unsupported_version(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, _make_catalog(version=99))
        with pytest.raises(CatalogValidationError, match="version"):
            load_catalog_from_path(path)

    def test_missing_top_level_version(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, {"providers": [_minimal_provider()]})
        with pytest.raises(CatalogValidationError):
            load_catalog_from_path(path)

    def test_missing_providers_key(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, {"version": 1})
        with pytest.raises(CatalogValidationError):
            load_catalog_from_path(path)


class TestImmutability:
    """Frozen dataclasses reject attribute assignment."""

    def test_catalog_is_frozen(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, _make_catalog())
        catalog = load_catalog_from_path(path)

        with pytest.raises(FrozenInstanceError):
            catalog.version = 2  # type: ignore[misc]

    def test_provider_spec_is_frozen(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, _make_catalog())
        catalog = load_catalog_from_path(path)
        provider = catalog.providers[0]

        with pytest.raises(FrozenInstanceError):
            provider.id = "mutated"  # type: ignore[misc]

    def test_model_spec_is_frozen(self, tmp_path: Path) -> None:
        path = _write_catalog(tmp_path, _make_catalog())
        catalog = load_catalog_from_path(path)
        model = catalog.providers[0].models[0]

        with pytest.raises(FrozenInstanceError):
            model.context_window_tokens = 0  # type: ignore[misc]


class TestLoadBuiltinCatalog:
    """Tests for load_builtin_catalog()."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.catalog = load_builtin_catalog()

    def test_returns_valid_catalog(self) -> None:
        assert isinstance(self.catalog, LLMCatalog)
        assert self.catalog.version == 1

    def test_has_exactly_four_providers(self) -> None:
        assert len(self.catalog.providers) == 4
        ids = {p.id for p in self.catalog.providers}
        assert ids == {"anthropic", "openai", "deepseek", "zhipu"}

    # -- Anthropic --

    def test_anthropic_provider(self) -> None:
        p = self.catalog.get_provider("anthropic")
        assert p.display_name == "Anthropic"
        assert p.provider_type == "anthropic"
        assert p.base_url == "https://api.anthropic.com"
        assert len(p.models) == 3

    def test_anthropic_opus_47(self) -> None:
        m = self.catalog.get_model("anthropic", "claude-opus-4-7")
        assert m.display_name == "Claude Opus 4.7"
        assert m.context_window_tokens == 1_000_000
        assert m.thinking_capability == "adaptive"
        assert m.thinking_format is None

    def test_anthropic_sonnet_46(self) -> None:
        m = self.catalog.get_model("anthropic", "claude-sonnet-4-6")
        assert m.display_name == "Claude Sonnet 4.6"
        assert m.context_window_tokens == 1_000_000
        assert m.thinking_capability == "adaptive"

    def test_anthropic_haiku_45(self) -> None:
        m = self.catalog.get_model("anthropic", "claude-haiku-4-5")
        assert m.display_name == "Claude Haiku 4.5"
        assert m.context_window_tokens == 200_000
        assert m.thinking_capability == "none"

    # -- OpenAI --

    def test_openai_provider(self) -> None:
        p = self.catalog.get_provider("openai")
        assert p.display_name == "OpenAI"
        assert p.provider_type == "openai"
        assert p.base_url == "https://api.openai.com/v1"
        assert len(p.models) == 2

    def test_openai_gpt55(self) -> None:
        m = self.catalog.get_model("openai", "gpt-5.5")
        assert m.display_name == "GPT-5.5"
        assert m.context_window_tokens == 1_050_000
        assert m.thinking_capability == "effort"

    def test_openai_gpt54(self) -> None:
        m = self.catalog.get_model("openai", "gpt-5.4")
        assert m.display_name == "GPT-5.4"
        assert m.context_window_tokens == 1_050_000
        assert m.thinking_capability == "effort"

    # -- DeepSeek --

    def test_deepseek_provider(self) -> None:
        p = self.catalog.get_provider("deepseek")
        assert p.display_name == "DeepSeek"
        assert p.provider_type == "openai"
        assert p.base_url == "https://api.deepseek.com"
        assert len(p.models) == 2

    def test_deepseek_v4_pro(self) -> None:
        m = self.catalog.get_model("deepseek", "deepseek-v4-pro")
        assert m.display_name == "DeepSeek V4 Pro"
        assert m.context_window_tokens == 1_000_000
        assert m.thinking_capability == "toggle"
        assert m.thinking_format == "reasoning_content"

    def test_deepseek_v4_flash(self) -> None:
        m = self.catalog.get_model("deepseek", "deepseek-v4-flash")
        assert m.display_name == "DeepSeek V4 Flash"
        assert m.thinking_capability == "toggle"
        assert m.thinking_format == "reasoning_content"

    # -- Zhipu --

    def test_zhipu_provider(self) -> None:
        p = self.catalog.get_provider("zhipu")
        assert p.display_name == "Zhi Pu Coding"
        assert p.provider_type == "anthropic"
        assert p.base_url == "https://open.bigmodel.cn/api/anthropic"
        assert len(p.models) == 3

    def test_zhipu_glm51(self) -> None:
        m = self.catalog.get_model("zhipu", "glm-5.1")
        assert m.display_name == "GLM-5.1"
        assert m.context_window_tokens == 200_000
        assert m.thinking_capability == "toggle"
        assert m.thinking_format is None

    def test_zhipu_glm5v_turbo(self) -> None:
        m = self.catalog.get_model("zhipu", "glm-5v-turbo")
        assert m.display_name == "GLM-5V-Turbo"
        assert m.context_window_tokens == 200_000
        assert m.thinking_capability == "toggle"

    def test_zhipu_glm47(self) -> None:
        m = self.catalog.get_model("zhipu", "glm-4.7")
        assert m.display_name == "GLM-4.7"
        assert m.context_window_tokens == 200_000
        assert m.thinking_capability == "toggle"
        assert m.thinking_format is None
