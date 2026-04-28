from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_PROVIDER_TYPES = {"anthropic", "openai"}
SUPPORTED_THINKING_CAPABILITIES = {
    "none",
    "toggle",
    "effort",
    "adaptive",
    "output_effort",
    "always_on",
    None,
}
SUPPORTED_THINKING_FORMATS = {"reasoning_content", "think_tags", None}

MIN_CONTEXT_WINDOW = 1_000
MAX_CONTEXT_WINDOW = 10_000_000


class CatalogValidationError(ValueError):
    """Raised when a catalog JSON file fails structural or semantic validation."""


@dataclass(frozen=True, slots=True)
class LLMModelSpec:
    id: str
    display_name: str
    context_window_tokens: int
    thinking_capability: str | None
    thinking_format: str | None
    supports_image_input: bool = False
    supports_text_file_input: bool = True


@dataclass(frozen=True, slots=True)
class LLMProviderSpec:
    id: str
    display_name: str
    provider_type: str
    base_url: str
    models: tuple[LLMModelSpec, ...]


@dataclass(frozen=True, slots=True)
class LLMCatalog:
    version: int
    providers: tuple[LLMProviderSpec, ...]

    def get_provider(self, provider_id: str) -> LLMProviderSpec:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        raise KeyError(provider_id)

    def get_model(self, provider_id: str, model_id: str) -> LLMModelSpec:
        provider = self.get_provider(provider_id)
        for model in provider.models:
            if model.id == model_id:
                return model
        raise KeyError(f"{provider_id}/{model_id}")


def _parse_model(raw: dict[str, Any]) -> LLMModelSpec:
    return LLMModelSpec(
        id=raw["id"],
        display_name=raw["display_name"],
        context_window_tokens=raw["context_window_tokens"],
        thinking_capability=raw.get("thinking_capability"),
        thinking_format=raw.get("thinking_format"),
        supports_image_input=raw.get("supports_image_input", False),
        supports_text_file_input=raw.get("supports_text_file_input", True),
    )


def _validate_catalog(data: dict[str, Any]) -> None:
    if "version" not in data:
        raise CatalogValidationError("Missing top-level 'version'")
    if data["version"] != 1:
        raise CatalogValidationError(
            f"Unsupported catalog version: {data['version']!r} (expected 1)"
        )
    if "providers" not in data:
        raise CatalogValidationError("Missing top-level 'providers'")

    providers_raw = data["providers"]
    if not isinstance(providers_raw, list):
        raise CatalogValidationError("'providers' must be a list")

    seen_provider_ids: set[str] = set()
    for prov in providers_raw:
        if not isinstance(prov, dict):
            raise CatalogValidationError("Each provider must be a JSON object")

        pid = prov.get("id")
        if not isinstance(pid, str):
            raise CatalogValidationError(f"Provider id must be a string, got {pid!r}")
        if pid in seen_provider_ids:
            raise CatalogValidationError(f"Duplicate provider id: {pid!r}")
        seen_provider_ids.add(pid)

        ptype = prov.get("provider_type")
        if ptype not in SUPPORTED_PROVIDER_TYPES:
            raise CatalogValidationError(
                f"Unsupported provider_type {ptype!r} for provider {pid!r}"
            )

        models_raw = prov.get("models")
        if not isinstance(models_raw, list):
            raise CatalogValidationError(f"Provider {pid!r} 'models' must be a list")

        seen_model_ids: set[str] = set()
        for m in models_raw:
            if not isinstance(m, dict):
                raise CatalogValidationError(
                    f"Each model in provider {pid!r} must be a JSON object"
                )

            mid = m.get("id")
            if not isinstance(mid, str):
                raise CatalogValidationError(
                    f"Model id must be a string in provider {pid!r}, got {mid!r}"
                )
            if mid in seen_model_ids:
                raise CatalogValidationError(f"Duplicate model id {mid!r} in provider {pid!r}")
            seen_model_ids.add(mid)

            cwt = m.get("context_window_tokens")
            if not isinstance(cwt, int) or cwt < MIN_CONTEXT_WINDOW or cwt > MAX_CONTEXT_WINDOW:
                raise CatalogValidationError(
                    f"context_window_tokens for {pid!r}/{mid!r} must be an int "
                    f"in [{MIN_CONTEXT_WINDOW}, {MAX_CONTEXT_WINDOW}], got {cwt!r}"
                )

            tc = m.get("thinking_capability")
            if tc not in SUPPORTED_THINKING_CAPABILITIES:
                raise CatalogValidationError(
                    f"Unsupported thinking_capability {tc!r} for model {pid!r}/{mid!r}"
                )

            tf = m.get("thinking_format")
            if tf not in SUPPORTED_THINKING_FORMATS:
                raise CatalogValidationError(
                    f"Unsupported thinking_format {tf!r} for model {pid!r}/{mid!r}"
                )


def _build_catalog(data: dict[str, Any]) -> LLMCatalog:
    providers: list[LLMProviderSpec] = []
    for prov in data["providers"]:
        models = tuple(_parse_model(m) for m in prov["models"])
        providers.append(
            LLMProviderSpec(
                id=prov["id"],
                display_name=prov["display_name"],
                provider_type=prov["provider_type"],
                base_url=prov["base_url"],
                models=models,
            )
        )
    return LLMCatalog(version=data["version"], providers=tuple(providers))


def load_catalog_from_path(path: Path) -> LLMCatalog:
    """Load and validate a catalog JSON file from *path*."""
    if not path.exists():
        raise FileNotFoundError(path)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogValidationError(f"Invalid JSON in {path}: {exc}") from exc

    _validate_catalog(data)
    return _build_catalog(data)


def load_builtin_catalog() -> LLMCatalog:
    """Load the bundled ``builtin_providers.json`` catalog."""
    ref = importlib.resources.files("sebastian.llm.catalog").joinpath("builtin_providers.json")
    data = json.loads(ref.read_text(encoding="utf-8"))
    _validate_catalog(data)
    return _build_catalog(data)
