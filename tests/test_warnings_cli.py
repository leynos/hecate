"""CLI and configuration tests for warning-level dependency directions.

Warnings are a policy declaration, so most of what can go wrong is a
configuration mistake: a target no group declares, a target that is also
allowed, or a malformed list. The rest is exit-status behaviour, which has to
keep the warning visible in the output of the run it fails.
"""

from __future__ import annotations

import dataclasses as dc
import json
import typing as typ
from pathlib import Path

import pytest

from hecate.cli import main
from hecate.config import ConfigError, load_config

if typ.TYPE_CHECKING:
    from _pytest.capture import CaptureFixture


def _group(
    name: str,
    prefix: str,
    *,
    allowed: str | None = None,
    warn: str | None = None,
) -> str:
    """Render one ``[[tool.hecate.groups]]`` stanza as TOML text.

    ``allowed`` and ``warn`` are TOML array literals written as text rather
    than as Python sequences, so a test states the exact source a user would
    write — including a malformed one the parser is expected to reject.
    ``allowed`` defaults to the group's own name, which every stanza here but
    the rejection cases does.
    """
    allowed_text = allowed if allowed is not None else f'["{name}"]'
    lines = [
        "[[tool.hecate.groups]]",
        f'name = "{name}"',
        f'prefixes = ["{prefix}"]',
        f"allowed = {allowed_text}",
    ]
    if warn is not None:
        lines.append(f"warn = {warn}")
    return "\n".join(lines) + "\n"


#: The head table every config in this module shares. Warnings are a group
#: key, so nothing but the group stanzas varies between the cases here.
_HEAD = """
[tool.hecate]
root_packages = ["pkg"]
"""


def _config(*groups: str) -> str:
    """Compose a policy config from the head table and group stanzas."""
    return _HEAD + "".join(groups)


#: The policy under test: ``application`` tolerates ``adapter`` at warning
#: level. Every run in this module either uses this pair or adds to it.
_WARN_GROUPS = (
    _group("application", "pkg.application", warn='["adapter"]'),
    _group("adapter", "pkg.adapters"),
)


def _assert_config_rejects(
    tmp_path: Path,
    toml_text: str,
    *expected_substrings: str,
) -> None:
    """Scaffold a temp config and assert ``load_config`` raises ``ConfigError``.

    The config file path and every string in *expected_substrings* must appear in
    the resulting error message.
    """
    config = tmp_path / "pyproject.toml"
    (tmp_path / "pkg").mkdir(exist_ok=True)
    config.write_text(toml_text, encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(config)

    error_text = str(exc_info.value)
    assert str(config) in error_text, (
        f"expected config path {config!r} in error message: {error_text}"
    )
    for expected in expected_substrings:
        assert expected in error_text, (
            f"expected {expected!r} in error message: {error_text}"
        )


def test_config_validation_rejects_unknown_warn_group(tmp_path: Path) -> None:
    """Policy validation reports undeclared warning targets.

    A warning target that no group declares can never be reached, so it would
    silently tolerate nothing. Rejecting it keeps the migration list honest.
    """
    _assert_config_rejects(
        tmp_path,
        _config(_group("domain", "pkg.domain", warn='["legacy"]')),
        "undeclared groups",
        "legacy",
    )


def test_config_validation_rejects_allowed_and_warn_overlap(tmp_path: Path) -> None:
    """A target cannot be both allowed and warned.

    Allowed means silent and warned means reported; accepting both would make
    the outcome depend on which check ran first rather than on the config.
    """
    _assert_config_rejects(
        tmp_path,
        _config(
            _group(
                "domain",
                "pkg.domain",
                allowed='["domain", "application"]',
                warn='["application"]',
            ),
            _group("application", "pkg.application"),
        ),
        "group domain",
        "both allowed and warn",
        "application",
    )


def test_config_validation_rejects_non_list_warn(tmp_path: Path) -> None:
    """A ``warn`` value that is not a string list is a configuration error."""
    _assert_config_rejects(
        tmp_path,
        _config(_group("domain", "pkg.domain", warn='"legacy"')),
        "must be a string list",
    )


def test_config_validation_rejects_blank_warn_entry(tmp_path: Path) -> None:
    """A blank warning target cannot match a group and is rejected."""
    _assert_config_rejects(
        tmp_path,
        _config(_group("domain", "pkg.domain", warn='["  "]')),
        "must be a string list",
    )


def test_config_accepts_absent_and_empty_warn_lists(tmp_path: Path) -> None:
    """An omitted ``warn`` key and an explicit empty list both mean no warnings.

    Existing configurations predate the key, so omitting it has to keep
    working; an empty list is how a migration records that it has finished.
    """
    (tmp_path / "pkg").mkdir()
    config = tmp_path / "pyproject.toml"
    config.write_text(
        _config(
            _group("domain", "pkg.domain"),
            _group("legacy", "pkg.legacy", warn="[]"),
        ),
        encoding="utf-8",
    )

    hecate_config = load_config(config)

    warn_lists = {group.name: group.warn for group in hecate_config.policy.groups}
    assert warn_lists == {"domain": (), "legacy": ()}, (
        f"expected empty warning lists, got {warn_lists!r}"
    )


def _write_package(root: Path, files: dict[str, str]) -> None:
    """Write a scratch package tree from relative paths to source text."""
    for relative_path, contents in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")


def _write_config(tmp_path: Path, toml_text: str) -> Path:
    """Write a TOML config into an existing scratch package directory."""
    config = tmp_path / "pyproject.toml"
    config.write_text(toml_text, encoding="utf-8")
    return config


#: The scanned package the CLI tests share: ``application`` imports the
#: adapter, and that is the one edge the warning policies tolerate.
_PACKAGE_FILES = {
    "__init__.py": "",
    "application/__init__.py": "",
    "application/service.py": "from pkg.adapters import database\n",
    "adapters/__init__.py": "",
    "adapters/database.py": "",
}


@dc.dataclass(frozen=True, slots=True)
class CliRun:
    """One finished CLI invocation, as the assertions need to see it."""

    exit_code: int
    stdout: str
    stderr: str


def _run_checker(config: Path, capsys: CaptureFixture[str], *args: str) -> CliRun:
    """Run the checker over one config and capture its exit code and output."""
    exit_code = main(["check", "--config", str(config), *args])
    captured = capsys.readouterr()
    return CliRun(exit_code=exit_code, stdout=captured.out, stderr=captured.err)


@pytest.fixture
def warned_edge_config(tmp_path: Path) -> Path:
    """Create a package with one edge tolerated at warning level.

    ``application`` warns ``adapter``, so the single import in the package is
    classified, reported, and passes on its own. The policy is what the CLI
    warning tests exercise; nothing else about the package is interesting.
    """
    _write_package(tmp_path / "pkg", _PACKAGE_FILES)
    return _write_config(tmp_path, _config(*_WARN_GROUPS))


def test_cli_passes_with_warnings_by_default(
    warned_edge_config: Path, capsys: CaptureFixture[str]
) -> None:
    """A warned edge exits 0 and still reports itself.

    The whole point of the severity is that the migration can land without a
    red build, so exit code 0 and a visible diagnostic have to hold together.
    """
    run = _run_checker(warned_edge_config, capsys)

    assert run.exit_code == 0, f"a warning must not fail by default, got {run!r}"
    assert "(warning):" in run.stdout, f"expected the warned edge, got {run!r}"


def test_cli_fail_on_warnings_fails_a_warning_only_run(
    warned_edge_config: Path, capsys: CaptureFixture[str]
) -> None:
    """``--fail-on-warnings`` turns a warning-only run into exit code 1.

    The output is emitted before the exit code is decided, so a run that fails
    on warnings still shows which edges caused it.
    """
    run = _run_checker(warned_edge_config, capsys, "--fail-on-warnings")

    assert run.exit_code == 1, f"expected the flag to fail the run, got {run!r}"
    assert "(warning):" in run.stdout, (
        f"expected the warned edge to survive into the failing run, got {run!r}"
    )
    assert "architecture check passed" not in run.stdout, (
        f"a run that exits 1 must not claim it passed, got {run!r}"
    )


def test_cli_fail_on_warnings_reports_unmet_status_in_json(
    warned_edge_config: Path, capsys: CaptureFixture[str]
) -> None:
    """JSON marks an enforced warning run as unmet rather than passed.

    ``ok`` describes the architecture result and deliberately ignores
    warnings, so the command outcome needs its own key. Without it a machine
    consumer reads ``ok: true`` from a run whose exit code is 1.
    """
    run = _run_checker(
        warned_edge_config, capsys, "--fail-on-warnings", "--format", "json"
    )

    payload = json.loads(run.stdout)
    assert run.exit_code == 1, f"expected the flag to fail the run, got {run!r}"
    assert payload["ok"] is True, (
        f"warnings must not clear the architecture result, got {payload!r}"
    )
    assert payload["status"] == "failed", (
        f"the command outcome must reflect the exit code, got {payload!r}"
    )


def test_cli_json_reports_warning_severity_and_ok(
    warned_edge_config: Path, capsys: CaptureFixture[str]
) -> None:
    """JSON carries the warning with its severity while ``ok`` stays true."""
    run = _run_checker(warned_edge_config, capsys, "--format", "json")

    payload = json.loads(run.stdout)
    assert run.exit_code == 0, f"expected exit code 0, got {run!r}"
    assert payload["ok"] is True, f"a warning must not clear ok, got {payload!r}"
    assert payload["violations"] == [], (
        f"a warned edge must not appear as a violation, got {payload!r}"
    )
    warnings = payload["warnings"]
    # ``from pkg.adapters import database`` reaches both the module and the
    # symbol through it, and both edges are warned.
    assert [entry["imported"] for entry in warnings] == [
        "pkg.adapters",
        "pkg.adapters.database",
    ], f"expected both expanded edges as warnings, got {warnings!r}"
    assert all(entry["severity"] == "warning" for entry in warnings), (
        f"expected warning severity on every entry, got {warnings!r}"
    )


def test_cli_json_reports_empty_warnings_for_unconfigured_policy(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A policy without warning targets reports an empty warnings list."""
    _write_package(tmp_path / "pkg", {"__init__.py": ""})
    config = _write_config(tmp_path, _config(_group("pkg", "pkg")))

    run = _run_checker(config, capsys, "--format", "json")

    payload = json.loads(run.stdout)
    assert run.exit_code == 0, f"expected exit code 0, got {run!r}"
    assert payload["warnings"] == [], (
        f"expected an empty warnings list, got {payload!r}"
    )


def test_cli_warnings_and_violations_fail_the_run(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    """A violated edge still fails the run when warnings are also present."""
    _write_package(
        tmp_path / "pkg",
        {
            **_PACKAGE_FILES,
            "domain/__init__.py": "",
            "domain/model.py": "from pkg.adapters import database\n",
        },
    )
    config = _write_config(
        tmp_path,
        _config(_group("domain", "pkg.domain"), *_WARN_GROUPS),
    )

    run = _run_checker(config, capsys)

    assert run.exit_code == 1, f"a violation must fail the run, got {run!r}"
    assert "pkg.domain.model:1 imports forbidden" in run.stdout, (
        f"expected the violation in stdout, got {run!r}"
    )
    assert "(warning):" in run.stdout, (
        f"expected the warning beside the violation, got {run!r}"
    )
