from __future__ import annotations

from pathlib import Path

import httpx
from typer.testing import CliRunner

from sebastian.cli import skills
from sebastian.main import app
from sebastian.skills_registry.installer import SkillInstallError
from sebastian.skills_registry.lockfile import LockfileError
from sebastian.skills_registry.models import (
    InstalledSkill,
    InstallResult,
    LocalSkillDetail,
    RemoveResult,
    SkillDetail,
)

runner = CliRunner()


def test_search_defaults_to_local_without_registry_call(monkeypatch, tmp_path: Path) -> None:
    registry_calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "RegistryClient",
        lambda registry=None: registry_calls.append(registry or ""),
    )
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="weather",
                registered_name="skill__weather",
                version="1.0.0",
                registry="https://clawhub.ai",
                managed=True,
                path=tmp_path / "weather",
                source="managed",
                description="Weather helper",
            ),
            InstalledSkill(
                slug="flight",
                registered_name="skill__flight",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "flight",
                source="unmanaged",
                description="Flight helper",
            ),
        ],
    )

    result = runner.invoke(app, ["skills", "search", "weather"])

    assert result.exit_code == 0
    assert registry_calls == []
    assert "LOCAL" in result.output
    assert "weather\tmanaged\tskill__weather\tWeather helper" in result.output
    assert "flight" not in result.output


def test_search_explicit_local_does_not_call_registry(monkeypatch, tmp_path: Path) -> None:
    registry_calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "RegistryClient",
        lambda registry=None: registry_calls.append(registry or ""),
    )
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="weather",
                registered_name="skill__weather",
                version="1.0.0",
                registry="https://clawhub.ai",
                managed=True,
                path=tmp_path / "weather",
                source="managed",
                description="Weather helper",
            )
        ],
    )

    result = runner.invoke(
        app,
        ["skills", "search", "weather", "--source", "local"],
    )

    assert result.exit_code == 0
    assert registry_calls == []
    assert "LOCAL" in result.output
    assert "REGISTRY" not in result.output


def test_search_registry_source_calls_registry(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_search(
        query: str,
        registry: str | None = None,
    ) -> list[tuple[str, str | None, str | None, str]]:
        calls.append((query, registry))
        return [("weather", "1.2.3", "reviewed", "Weather helper")]

    monkeypatch.setattr(skills, "search_registry", fake_search)

    result = runner.invoke(
        app,
        ["skills", "search", "weather", "--source", "registry"],
    )

    assert result.exit_code == 0
    assert calls == [("weather", None)]
    assert "REGISTRY" in result.output
    assert "weather\t1.2.3/reviewed\tWeather helper" in result.output


def test_search_all_prints_local_and_registry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="weather",
                registered_name="skill__weather",
                version="1.0.0",
                registry="https://clawhub.ai",
                managed=True,
                path=tmp_path / "weather",
                source="managed",
                description="Weather helper",
            )
        ],
    )
    monkeypatch.setattr(
        skills,
        "search_registry",
        lambda query, registry=None: [
            ("weather-pro", "2.0.0", "reviewed", "Advanced weather")
        ],
    )

    result = runner.invoke(app, ["skills", "search", "weather", "--source", "all"])

    assert result.exit_code == 0
    assert "LOCAL" in result.output
    assert "weather\tmanaged\tskill__weather\tWeather helper" in result.output
    assert "REGISTRY" in result.output
    assert "weather-pro\t2.0.0/reviewed\tAdvanced weather" in result.output


def test_search_registry_option_does_not_imply_network_for_default_local(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "RegistryClient",
        lambda registry=None: registry_calls.append(registry or ""),
    )
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="weather",
                registered_name="skill__weather",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "weather",
                source="unmanaged",
                description="Weather helper",
            )
        ],
    )

    result = runner.invoke(
        app,
        ["skills", "search", "weather", "--registry", "https://mirror.example"],
    )

    assert result.exit_code == 0
    assert registry_calls == []
    assert "LOCAL" in result.output


def test_search_registry_option_does_not_imply_network_for_explicit_local(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registry_calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "RegistryClient",
        lambda registry=None: registry_calls.append(registry or ""),
    )
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="weather",
                registered_name="skill__weather",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "weather",
                source="unmanaged",
                description="Weather helper",
            )
        ],
    )

    result = runner.invoke(
        app,
        [
            "skills",
            "search",
            "weather",
            "--source",
            "local",
            "--registry",
            "https://mirror.example",
        ],
    )

    assert result.exit_code == 0
    assert registry_calls == []
    assert "LOCAL" in result.output


def test_search_local_matches_description(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="weather",
                registered_name="skill__weather",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "weather",
                source="unmanaged",
                description="Rain forecast helper",
            )
        ],
    )

    result = runner.invoke(app, ["skills", "search", "forecast"])

    assert result.exit_code == 0
    assert "weather\tunmanaged\tskill__weather\tRain forecast helper" in result.output


def test_search_local_multi_token_query_matches_any_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="flight_search",
                registered_name="skill__flight_search",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "flight_search",
                source="unmanaged",
                description="Find flight and airfare options",
                name="flight_search",
            )
        ],
    )

    result = runner.invoke(app, ["skills", "search", "机票 航班 flight airfare"])

    assert result.exit_code == 0
    assert (
        "flight_search\tunmanaged\tskill__flight_search\tFind flight and airfare options"
    ) in result.output


def test_search_local_matches_frontmatter_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="travel-pack",
                registered_name="skill__travel_pack",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "travel-pack",
                source="unmanaged",
                description="Travel helper",
                name="airfare",
            )
        ],
    )

    result = runner.invoke(app, ["skills", "search", "airfare"])

    assert result.exit_code == 0
    assert "travel-pack\tunmanaged\tskill__travel_pack\tTravel helper" in result.output


def test_search_local_filters_ascii_stopwords(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="article_formatter",
                registered_name="skill__article_formatter",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "article_formatter",
                source="unmanaged",
                description="Convert a note to a formatted article",
                name="article_formatter",
            ),
        ],
    )

    result = runner.invoke(app, ["skills", "search", "book a flight to Tokyo"])

    assert result.exit_code == 0
    assert result.output == "LOCAL\n"


def test_search_local_keeps_short_ascii_exact_slug(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="ci",
                registered_name="skill__ci",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "ci",
                source="unmanaged",
                description="Continuous integration helper",
                name="ci",
            ),
        ],
    )

    result = runner.invoke(app, ["skills", "search", "ci"])

    assert result.exit_code == 0
    assert "ci\tunmanaged\tskill__ci\tContinuous integration helper" in result.output


def test_search_local_sorts_stronger_name_match_before_description_match(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="generic_travel",
                registered_name="skill__generic_travel",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "generic_travel",
                source="unmanaged",
                description="airfare comparison helper",
                name="generic_travel",
            ),
            InstalledSkill(
                slug="flight_search",
                registered_name="skill__flight_search",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "flight_search",
                source="unmanaged",
                description="travel helper",
                name="airfare",
            ),
        ],
    )

    result = runner.invoke(app, ["skills", "search", "airfare"])

    assert result.exit_code == 0
    assert result.output.index("flight_search") < result.output.index("generic_travel")


def test_search_local_exact_slug_and_name_match_beat_accumulated_weaker_fields(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="airfare-helper",
                registered_name="skill__airfare_helper",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "airfare-helper",
                source="unmanaged",
                description="airfare planning helper",
                name="travel_helper",
            ),
            InstalledSkill(
                slug="airfare",
                registered_name="skill__exact_slug",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "airfare",
                source="unmanaged",
                description="travel helper",
                name="exact_slug",
            ),
            InstalledSkill(
                slug="flight_search",
                registered_name="skill__flight_search",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "flight_search",
                source="unmanaged",
                description="travel helper",
                name="airfare",
            ),
        ],
    )

    result = runner.invoke(app, ["skills", "search", "airfare"])

    assert result.exit_code == 0
    assert result.output.index("airfare\t") < result.output.index("airfare-helper")
    assert result.output.index("flight_search") < result.output.index("airfare-helper")


def test_search_local_same_score_uses_source_priority_then_slug(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="zeta_travel",
                registered_name="skill__zeta_travel",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "zeta_travel",
                source="unmanaged",
                description="travel planning",
                name="zeta_travel",
            ),
            InstalledSkill(
                slug="beta_travel",
                registered_name="skill__beta_travel",
                version=None,
                registry=None,
                managed=True,
                path=tmp_path / "beta_travel",
                source="managed",
                description="travel planning",
                name="beta_travel",
            ),
            InstalledSkill(
                slug="alpha_travel",
                registered_name="skill__alpha_travel",
                version=None,
                registry=None,
                managed=True,
                path=tmp_path / "alpha_travel",
                source="managed",
                description="travel planning",
                name="alpha_travel",
            ),
            InstalledSkill(
                slug="omega_travel",
                registered_name="skill__omega_travel",
                version=None,
                registry=None,
                managed=True,
                path=tmp_path / "omega_travel",
                source="builtin",
                description="travel planning",
                name="omega_travel",
            ),
        ],
    )

    result = runner.invoke(app, ["skills", "search", "planning"])

    assert result.exit_code == 0
    assert result.output.index("omega_travel") < result.output.index("alpha_travel")
    assert result.output.index("alpha_travel") < result.output.index("beta_travel")
    assert result.output.index("beta_travel") < result.output.index("zeta_travel")


def test_search_local_whitespace_query_prints_empty_local_section(
    monkeypatch,
) -> None:
    calls = 0

    def fake_list_installed() -> list[InstalledSkill]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(skills, "list_installed", fake_list_installed)

    result = runner.invoke(app, ["skills", "search", "   "])

    assert result.exit_code == 0
    assert result.output == "LOCAL\n"
    assert calls == 0


def test_search_registry_http_error_prints_clean_cli_error(monkeypatch) -> None:
    def fail_search(
        query: str,
        registry: str | None = None,
    ) -> list[tuple[str, str | None, str | None, str]]:
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(skills, "search_registry", fail_search)

    result = runner.invoke(
        app,
        ["skills", "search", "weather", "--source", "registry"],
    )

    assert result.exit_code == 1
    assert "❌ network down" in result.stderr


def test_install_prints_registered_name_and_immediate_availability_hint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        skills,
        "install_skill",
        lambda slug, *, version, registry, force: InstallResult(
            slug=slug,
            registered_name="weather_tool",
            version=version,
            path=tmp_path / slug,
        ),
    )

    result = runner.invoke(app, ["skills", "install", "weather"])

    assert result.exit_code == 0
    assert "weather_tool" in result.output
    assert "available immediately" in result.output
    assert "new Sebastian sessions" not in result.output


def test_install_propagates_version_registry_and_force(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_install(
        slug: str,
        *,
        version: str | None,
        registry: str | None,
        force: bool,
    ) -> InstallResult:
        calls.append(
            {
                "slug": slug,
                "version": version,
                "registry": registry,
                "force": force,
            }
        )
        return InstallResult(
            slug=slug,
            registered_name="weather_tool",
            version=version,
            path=tmp_path / slug,
        )

    monkeypatch.setattr(skills, "install_skill", fake_install)

    result = runner.invoke(
        app,
        [
            "skills",
            "install",
            "weather",
            "--version",
            "1.2.3",
            "--registry",
            "https://clawhub.ai",
            "--force",
        ],
        input="y\n",
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "slug": "weather",
            "version": "1.2.3",
            "registry": "https://clawhub.ai",
            "force": True,
        }
    ]


def test_inspect_prints_registry_details(monkeypatch) -> None:
    class FakeRegistryClient:
        def __init__(self, registry: str | None = None) -> None:
            self.registry = registry

        def inspect(self, slug: str, *, version: str | None = None) -> SkillDetail:
            return SkillDetail(
                slug=slug,
                name="Weather",
                description="Weather helper",
                version=version,
                download_url="https://clawhub.ai/weather.zip",
                sha256="abc123",
                security_status="approved",
                raw={},
            )

    monkeypatch.setattr(skills, "RegistryClient", FakeRegistryClient)

    result = runner.invoke(app, ["skills", "inspect", "weather", "--version", "1.2.3"])

    assert result.exit_code == 0
    assert "Slug: weather" in result.output
    assert "Version: 1.2.3" in result.output
    assert "Security: approved" in result.output


def test_install_with_custom_registry_can_be_declined(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "install_skill",
        lambda slug, *, version, registry, force: calls.append(slug),
    )

    result = runner.invoke(
        app,
        ["skills", "install", "weather", "--registry", "https://mirror.example"],
        input="n\n",
    )

    assert result.exit_code != 0
    assert calls == []


def test_install_with_env_custom_registry_can_be_declined(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setenv("SEBASTIAN_SKILLS_REGISTRY_URL", "https://mirror.example")
    monkeypatch.setattr(
        skills,
        "install_skill",
        lambda slug, *, version, registry, force: calls.append(slug),
    )

    result = runner.invoke(app, ["skills", "install", "weather"], input="n\n")

    assert result.exit_code != 0
    assert calls == []


def test_install_force_can_be_declined(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "install_skill",
        lambda slug, *, version, registry, force: calls.append(slug),
    )

    result = runner.invoke(
        app,
        ["skills", "install", "weather", "--force"],
        input="n\n",
    )

    assert result.exit_code != 0
    assert calls == []


def test_update_allow_rename_can_be_declined(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "update_skill",
        lambda slug, *, version, registry, force, allow_rename: calls.append(slug),
    )

    result = runner.invoke(
        app,
        ["skills", "update", "weather", "--allow-rename"],
        input="n\n",
    )

    assert result.exit_code != 0
    assert calls == []


def test_update_force_can_be_declined(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "update_skill",
        lambda slug, *, version, registry, force, allow_rename: calls.append(slug),
    )

    result = runner.invoke(
        app,
        ["skills", "update", "weather", "--force"],
        input="n\n",
    )

    assert result.exit_code != 0
    assert calls == []


def test_update_with_custom_registry_can_be_declined(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "update_skill",
        lambda slug, *, version, registry, force, allow_rename: calls.append(slug),
    )

    result = runner.invoke(
        app,
        ["skills", "update", "flight", "--registry", "https://mirror.example"],
        input="n\n",
    )

    assert result.exit_code != 0
    assert calls == []
    assert "Install" not in result.output


def test_update_with_stored_custom_registry_can_be_declined(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="flight",
                registered_name="skill__flight",
                version="1.0.0",
                registry="https://mirror.example",
                managed=True,
                path=tmp_path / "flight",
            )
        ],
    )
    monkeypatch.setattr(
        skills,
        "update_skill",
        lambda slug, *, version, registry, force, allow_rename: calls.append(slug),
    )

    result = runner.invoke(app, ["skills", "update", "flight"], input="n\n")

    assert result.exit_code != 0
    assert calls == []


def test_update_prints_registered_name_and_immediate_availability_hint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        skills,
        "update_skill",
        lambda slug, *, version, registry, force, allow_rename: InstallResult(
            slug=slug,
            registered_name="weather_tool",
            version=version,
            path=tmp_path / slug,
        ),
    )

    result = runner.invoke(app, ["skills", "update", "weather"])

    assert result.exit_code == 0
    assert "weather_tool" in result.output
    assert "available immediately" in result.output
    assert "new Sebastian sessions" not in result.output


def test_update_propagates_version_registry_force_and_allow_rename(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_update(
        slug: str,
        *,
        version: str | None,
        registry: str | None,
        force: bool,
        allow_rename: bool,
    ) -> InstallResult:
        calls.append(
            {
                "slug": slug,
                "version": version,
                "registry": registry,
                "force": force,
                "allow_rename": allow_rename,
            }
        )
        return InstallResult(
            slug=slug,
            registered_name="weather_tool",
            version=version,
            path=tmp_path / slug,
        )

    monkeypatch.setattr(skills, "update_skill", fake_update)

    result = runner.invoke(
        app,
        [
            "skills",
            "update",
            "weather",
            "--version",
            "1.2.3",
            "--registry",
            "https://clawhub.ai",
            "--force",
            "--allow-rename",
        ],
        input="y\ny\n",
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "slug": "weather",
            "version": "1.2.3",
            "registry": "https://clawhub.ai",
            "force": True,
            "allow_rename": True,
        }
    ]


def test_update_all_updates_managed_skills_and_skips_unmanaged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="flight",
                registered_name="skill__flight",
                version="1.0.0",
                registry="https://clawhub.ai",
                managed=True,
                path=tmp_path / "flight",
            ),
            InstalledSkill(
                slug="manual",
                registered_name="skill__manual",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "manual",
            ),
            InstalledSkill(
                slug="weather",
                registered_name="skill__weather",
                version="1.0.0",
                registry="https://clawhub.ai",
                managed=True,
                path=tmp_path / "weather",
            ),
        ],
    )

    def fake_update(
        slug: str,
        *,
        version: str | None,
        registry: str | None,
        force: bool,
        allow_rename: bool,
    ) -> InstallResult:
        calls.append(slug)
        return InstallResult(
            slug=slug,
            registered_name=f"skill__{slug}",
            version=version or "1.1.0",
            path=tmp_path / slug,
        )

    monkeypatch.setattr(skills, "update_skill", fake_update)

    result = runner.invoke(app, ["skills", "update", "--all"])

    assert result.exit_code == 0
    assert calls == ["flight", "weather"]
    assert "Updated 2 Skill(s); 0 failed." in result.output


def test_update_all_continues_failures_and_returns_nonzero(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="flight",
                registered_name="skill__flight",
                version="1.0.0",
                registry="https://clawhub.ai",
                managed=True,
                path=tmp_path / "flight",
            ),
            InstalledSkill(
                slug="weather",
                registered_name="skill__weather",
                version="1.0.0",
                registry="https://clawhub.ai",
                managed=True,
                path=tmp_path / "weather",
            ),
        ],
    )

    def fake_update(
        slug: str,
        *,
        version: str | None,
        registry: str | None,
        force: bool,
        allow_rename: bool,
    ) -> InstallResult:
        calls.append(slug)
        if slug == "flight":
            raise SkillInstallError("registry down")
        return InstallResult(
            slug=slug,
            registered_name=f"skill__{slug}",
            version=version or "1.1.0",
            path=tmp_path / slug,
        )

    monkeypatch.setattr(skills, "update_skill", fake_update)

    result = runner.invoke(app, ["skills", "update", "--all"])

    assert result.exit_code == 1
    assert calls == ["flight", "weather"]
    assert "Updated 1 Skill(s); 1 failed." in result.output
    assert "flight: registry down" in result.stderr


def test_remove_without_yes_can_be_declined(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        skills,
        "remove_installed_skill",
        lambda slug, *, yes: calls.append(slug),
    )

    result = runner.invoke(app, ["skills", "remove", "weather"], input="n\n")

    assert result.exit_code != 0
    assert calls == []


def test_remove_yes_skips_confirmation_and_calls_remove(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_remove(slug: str, *, yes: bool) -> RemoveResult:
        calls.append((slug, yes))
        return RemoveResult(slug=slug, registered_name="weather_tool", path=tmp_path / slug)

    monkeypatch.setattr(skills, "remove_installed_skill", fake_remove)

    result = runner.invoke(app, ["skills", "remove", "weather", "--yes"])

    assert result.exit_code == 0
    assert calls == [("weather", True)]
    assert "weather_tool" in result.output


def test_list_prints_managed_and_unmanaged_rows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        skills,
        "list_installed",
        lambda: [
            InstalledSkill(
                slug="managed",
                registered_name="managed_tool",
                version="1.0.0",
                registry="https://clawhub.ai",
                managed=True,
                path=tmp_path / "managed",
                source="managed",
            ),
            InstalledSkill(
                slug="manual",
                registered_name="manual_tool",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "manual",
                source="unmanaged",
            ),
        ],
    )

    result = runner.invoke(app, ["skills", "list"])

    assert result.exit_code == 0
    assert "managed\tmanaged_tool\t1.0.0\tmanaged" in result.output
    assert "manual\tmanual_tool\t-\tunmanaged" in result.output


def test_show_prints_local_skill_metadata_without_body_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_show(identifier: str, root: Path) -> LocalSkillDetail:
        assert identifier == "weather"
        return LocalSkillDetail(
            slug="weather",
            name="Weather",
            registered_name="skill__weather",
            description="Weather helper",
            body="Use this for weather.",
            files=("SKILL.md", "examples/demo.md"),
            version="1.0.0",
            registry="https://clawhub.ai",
            managed=True,
            source="managed",
            path=tmp_path / "weather",
        )

    monkeypatch.setattr(skills, "show_local_skill", fake_show)

    result = runner.invoke(app, ["skills", "show", "weather"])

    assert result.exit_code == 0
    assert "Slug: weather" in result.output
    assert "Registered: skill__weather" in result.output
    assert "Name: Weather" in result.output
    assert "Description: Weather helper" in result.output
    assert f"Path: {tmp_path / 'weather'}" in result.output
    assert "Source: managed" in result.output
    assert "Files:" in result.output
    assert "SKILL.md" in result.output
    assert "examples/demo.md" in result.output
    assert "Instructions:" not in result.output
    assert "Use this for weather." not in result.output


def test_show_with_body_prints_local_skill_instructions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_show(identifier: str, root: Path) -> LocalSkillDetail:
        assert identifier == "weather"
        return LocalSkillDetail(
            slug="weather",
            name="Weather",
            registered_name="skill__weather",
            description="Weather helper",
            body="Use this for weather.",
            files=("SKILL.md",),
            version="1.0.0",
            registry="https://clawhub.ai",
            managed=True,
            source="managed",
            path=tmp_path / "weather",
        )

    monkeypatch.setattr(skills, "show_local_skill", fake_show)

    result = runner.invoke(app, ["skills", "show", "weather", "--body"])

    assert result.exit_code == 0
    assert "Instructions:" in result.output
    assert "Use this for weather." in result.output


def test_show_with_body_rejects_large_skill_body(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_show(identifier: str, root: Path) -> LocalSkillDetail:
        assert identifier == "weather"
        return LocalSkillDetail(
            slug="weather",
            name="Weather",
            registered_name="skill__weather",
            description="Weather helper",
            body="x" * (skills.MAX_LOCAL_SKILL_READ_BYTES + 1),
            files=("SKILL.md",),
            version="1.0.0",
            registry="https://clawhub.ai",
            managed=True,
            source="managed",
            path=tmp_path / "weather",
        )

    monkeypatch.setattr(skills, "show_local_skill", fake_show)

    result = runner.invoke(app, ["skills", "show", "weather", "--body"])

    assert result.exit_code == 1
    assert "too large" in result.stderr
    assert "Instructions:" not in result.output


def test_read_prints_local_skill_file(monkeypatch) -> None:
    calls: list[tuple[str, str, Path]] = []

    def fake_read(identifier: str, relative_path: str, root: Path) -> str:
        calls.append((identifier, relative_path, root))
        return "# Example\nUse this sample.\n"

    monkeypatch.setattr(skills, "read_local_skill_file", fake_read)

    result = runner.invoke(app, ["skills", "read", "weather", "examples/demo.md"])

    assert result.exit_code == 0
    assert calls == [
        ("weather", "examples/demo.md", skills.settings.skills_extensions_dir)
    ]
    assert result.output == "# Example\nUse this sample.\n"


def test_list_lockfile_error_prints_clean_cli_error(monkeypatch) -> None:
    def fail_list() -> list[InstalledSkill]:
        raise LockfileError("bad lock")

    monkeypatch.setattr(skills, "list_installed", fail_list)

    result = runner.invoke(app, ["skills", "list"])

    assert result.exit_code == 1
    assert "❌ bad lock" in result.stderr


def test_install_errors_print_to_stderr(monkeypatch) -> None:
    def fail_install(slug: str, *, version: str | None, registry: str | None, force: bool) -> None:
        raise SkillInstallError("boom")

    monkeypatch.setattr(skills, "install_skill", fail_install)

    result = runner.invoke(app, ["skills", "install", "weather"])

    assert result.exit_code == 1
    assert "❌ boom" in result.stderr
