from __future__ import annotations

from pathlib import Path

import httpx
from typer.testing import CliRunner

from sebastian.cli import skills
from sebastian.main import app
from sebastian.skills_registry.installer import SkillInstallError
from sebastian.skills_registry.models import (
    InstalledSkill,
    InstallResult,
    RemoveResult,
    SkillDetail,
)

runner = CliRunner()


def test_search_prints_monkeypatched_registry_results(monkeypatch) -> None:
    monkeypatch.setattr(
        skills,
        "search_registry",
        lambda query, registry=None: [("weather", "Weather helper")],
    )

    result = runner.invoke(app, ["skills", "search", "weather"])

    assert result.exit_code == 0
    assert "weather\tWeather helper" in result.output


def test_search_http_error_prints_clean_cli_error(monkeypatch) -> None:
    def fail_search(query: str, registry: str | None = None) -> list[tuple[str, str]]:
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(skills, "search_registry", fail_search)

    result = runner.invoke(app, ["skills", "search", "weather"])

    assert result.exit_code == 1
    assert "❌ network down" in result.stderr


def test_install_prints_registered_name_and_new_session_hint(monkeypatch, tmp_path: Path) -> None:
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
    assert "new Sebastian sessions" in result.output


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


def test_update_prints_registered_name_and_new_session_hint(monkeypatch, tmp_path: Path) -> None:
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
    assert "new Sebastian sessions" in result.output


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
            ),
            InstalledSkill(
                slug="manual",
                registered_name="manual_tool",
                version=None,
                registry=None,
                managed=False,
                path=tmp_path / "manual",
            ),
        ],
    )

    result = runner.invoke(app, ["skills", "list"])

    assert result.exit_code == 0
    assert "managed\tmanaged_tool\t1.0.0\tmanaged" in result.output
    assert "manual\tmanual_tool\t-\tunmanaged" in result.output


def test_install_errors_print_to_stderr(monkeypatch) -> None:
    def fail_install(slug: str, *, version: str | None, registry: str | None, force: bool) -> None:
        raise SkillInstallError("boom")

    monkeypatch.setattr(skills, "install_skill", fail_install)

    result = runner.invoke(app, ["skills", "install", "weather"])

    assert result.exit_code == 1
    assert "❌ boom" in result.stderr
