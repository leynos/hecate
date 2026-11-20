"""Exercise CI's release-build and installed-wheel checks.

The release publishes whichever single ``.tar.gz`` sits beside the pure wheel,
so a pull request whose build produced none or two must fail there rather than
at tag time. These tests run the checked-in steps: the glob-count step against
zero, one, and two candidate files, and the installation step against a
synthetic wheel that either exposes the expected interface or deliberately does
not. The composite action is held to building both artefacts with one plain
``uv build``.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - the helper's return type only.
import sys
import typing as typ
from pathlib import Path

import pytest

from scripts import verify_installed_distribution as installed_distribution

from . import synthetic_distribution as synthetic
from .ci_workflows import ROOT, steps
from .release_workflow import link_scripts, run_bash, step, step_script

WORKFLOW = "ci.yml"
JOB = "wheel-build"
SDIST_STEP = "Require exactly one sdist to travel with the wheel"
VERIFY_STEP = "Verify the installed distribution"
ACTION = ROOT / ".github" / "actions" / "pure-python-wheel" / "action.yml"
POLICY = ROOT / "tests" / "fixtures" / "installed_cli" / "policy.toml"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="The CI workflow's steps run under Bash on Linux.",
)


def _run_with_sdist_count(tmp_path: Path, count: int) -> tuple[int, str]:
    """Run the count step with one pure wheel and ``count`` source distributions."""
    wheel_dir = tmp_path / "dist"
    wheel_dir.mkdir(parents=True)
    (wheel_dir / "hecate_enforce-1.0-py3-none-any.whl").touch()
    for index in range(count):
        (wheel_dir / f"hecate_enforce-1.0-{index}.tar.gz").touch()
    result = run_bash(
        step_script(JOB, SDIST_STEP, workflow=WORKFLOW),
        tmp_path,
        {"WHEEL_DIR": "dist"},
    )
    return result.returncode, result.stderr


def _run_verification(
    tmp_path: Path,
    *,
    wheel: Path | None = None,
    sdist: Path | None = None,
    version: str = "0.1.0",
) -> subprocess.CompletedProcess[str]:
    """Run the workflow's installation step against the staged archives."""
    directory = tmp_path / "dist"
    if wheel is None:
        wheel = synthetic.write_wheel(directory)
    if sdist is None:
        sdist = synthetic.write_sdist(directory, version=version)
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "hecate-enforce"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    link_scripts(tmp_path)
    return run_bash(
        step_script(JOB, VERIFY_STEP, workflow=WORKFLOW),
        tmp_path,
        {
            "WHEEL_DIR": "dist",
            "VENV_DIR": str(tmp_path / "venv"),
            "POLICY": str(POLICY),
        },
    )


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "fail"), (1, "pass"), (2, "fail")],
    ids=["no-sdist", "one-sdist", "two-sdists"],
)
def test_the_sdist_count_is_exactly_one(
    tmp_path: Path, count: int, expected: str
) -> None:
    """No sdist and two sdists are as wrong as each other; one alone passes."""
    returncode, stderr = _run_with_sdist_count(tmp_path, count)

    if expected == "pass":
        assert returncode == 0, stderr
        return
    assert returncode != 0, f"{count} sdists must fail the step, got {stderr!r}"
    assert "Expected exactly one source distribution." in stderr, (
        f"missing the expected diagnostic, got {stderr!r}"
    )


def test_the_wheel_count_is_also_exactly_one(tmp_path: Path) -> None:
    """A build that produced no wheel must fail rather than pass vacuously."""
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "hecate_enforce-1.0.tar.gz").touch()

    completed = run_bash(
        step_script(JOB, SDIST_STEP, workflow=WORKFLOW),
        tmp_path,
        {"WHEEL_DIR": "dist"},
    )

    assert completed.returncode != 0, "a build with no wheel must fail"
    assert "Expected exactly one pure Python wheel." in completed.stderr


def test_the_composite_action_builds_the_sdist_and_the_wheel() -> None:
    """A plain ``uv build`` builds the sdist first, then the wheel from it."""
    action = ACTION.read_text(encoding="utf-8")
    build = next(
        line.strip()
        for line in action.splitlines()
        if line.strip().startswith("uv build")
    )

    assert build == "uv build --out-dir dist", (
        "asking for one artefact would skip the proof that the sdist builds"
    )
    assert "*.tar.gz" in action, "the sdist must be uploaded with the wheel"
    assert "if-no-files-found: error" in action, (
        "a missing artefact must fail the build, not upload nothing"
    )


def test_the_installed_wheel_exposes_the_distribution_and_cli(
    tmp_path: Path,
) -> None:
    """The installed metadata, import, and both entry points all answer."""
    wheel = synthetic.write_wheel(tmp_path / "dist")

    completed = _run_verification(tmp_path, wheel=wheel)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "The archives and installed wheel expose the hecate-enforce interface." in (
        completed.stdout
    )


def test_the_verification_rejects_the_wrong_installed_distribution(
    tmp_path: Path,
) -> None:
    """A wheel installed under another name fails the metadata check."""
    wheel = synthetic.write_wheel(tmp_path / "dist", synthetic.WheelSpec(name="hecate"))

    completed = _run_verification(tmp_path, wheel=wheel)

    assert completed.returncode != 0, "the distribution name must be checked"
    assert "installed-distribution" in completed.stderr
    assert "hecate-enforce" in completed.stderr


def test_the_verification_rejects_an_sdist_with_another_name(
    tmp_path: Path,
) -> None:
    """The sdist's ``PKG-INFO`` must name the distribution, not just the wheel."""
    wheel = synthetic.write_wheel(tmp_path / "dist")
    sdist = synthetic.write_sdist(tmp_path / "dist", name="hecate")

    completed = _run_verification(tmp_path, wheel=wheel, sdist=sdist)

    assert completed.returncode != 0, "the sdist's name must be checked"
    assert "PKG-INFO" in completed.stderr, (
        "the failure must name the archive metadata that disagreed"
    )
    assert "hecate-enforce" in completed.stderr


def test_the_verification_reads_the_root_metadata_past_a_vendored_copy(
    tmp_path: Path,
) -> None:
    """A vendored archive member must not stand in for the archive's own."""
    wheel = synthetic.write_wheel(
        tmp_path / "dist", synthetic.WheelSpec(vendored="some-vendored-lib")
    )
    sdist = synthetic.write_sdist(tmp_path / "dist", vendored="some-vendored-lib")

    completed = _run_verification(tmp_path, wheel=wheel, sdist=sdist)

    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("archive", ["wheel", "sdist"], ids=["wheel", "sdist"])
def test_the_verification_judges_the_root_metadata_only(
    tmp_path: Path, archive: str
) -> None:
    """A correct vendored copy must not excuse the archive's own metadata."""
    if archive == "wheel":
        wheel = synthetic.write_wheel(
            tmp_path / "dist",
            synthetic.WheelSpec(name="hecate", vendored="hecate-enforce"),
        )
        sdist = synthetic.write_sdist(tmp_path / "dist")
    else:
        wheel = synthetic.write_wheel(tmp_path / "dist")
        sdist = synthetic.write_sdist(
            tmp_path / "dist", name="hecate", vendored="hecate-enforce"
        )

    completed = _run_verification(tmp_path, wheel=wheel, sdist=sdist)

    assert completed.returncode != 0, "the archive's own metadata is the subject"
    assert "hecate-enforce" in completed.stderr, (
        "the failure must name the distribution the root metadata should declare"
    )


def test_the_verification_rejects_an_archive_version_mismatch(
    tmp_path: Path,
) -> None:
    """Both archives must declare the version ``pyproject.toml`` states."""
    wheel = synthetic.write_wheel(tmp_path / "dist")
    sdist = synthetic.write_sdist(tmp_path / "dist")

    completed = _run_verification(tmp_path, wheel=wheel, sdist=sdist, version="0.2.0")

    assert completed.returncode != 0, "the declared version must be checked"
    assert "0.2.0" in completed.stderr, (
        "the failure must name the version pyproject.toml declares"
    )


def test_the_verification_judges_the_sdist_version_on_its_own(tmp_path: Path) -> None:
    """A correct wheel must not excuse an sdist that alone states another version.

    The wheel is the build's own 0.1.0 and ``pyproject.toml`` agrees with it,
    so only the sdist's ``PKG-INFO`` and filename disagree. A check that
    inspected one archive and inferred the other would pass here.
    """
    wheel = synthetic.write_wheel(tmp_path / "dist")
    sdist = synthetic.write_sdist(tmp_path / "dist", version="0.1.1")

    completed = _run_verification(tmp_path, wheel=wheel, sdist=sdist, version="0.1.0")

    assert completed.returncode != 0, "the sdist's own version must be checked"
    assert "0.1.1" in completed.stderr, (
        "the failure must name the version the sdist declares"
    )
    assert "0.1.0" in completed.stderr, (
        "the failure must name the version pyproject.toml declares"
    )


def test_verify_checks_the_installed_metadata_itself(tmp_path: Path) -> None:
    """``verify`` must ask the installed distribution for its own metadata.

    The stand-in interpreter accepts every command except the metadata query,
    so this fails if that query is ever dropped from ``verify``: with the query
    gone, every command succeeds and ``verify`` returns normally.
    """
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin" / "python"
    python.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  *importlib.metadata*) echo 'no hecate-enforce metadata' >&2; exit 1;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    hecate = venv / "bin" / "hecate"
    hecate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hecate.chmod(0o755)
    policy = tmp_path / "policy.toml"
    policy.write_text("", encoding="utf-8")

    with pytest.raises(installed_distribution.VerificationError) as raised:
        installed_distribution.verify(venv, policy)

    assert "importlib.metadata" in str(raised.value), (
        "the failure must be the metadata query, not another check"
    )


def test_the_verification_requires_exactly_one_sdist(tmp_path: Path) -> None:
    """A second source distribution is ambiguous, so the check refuses it."""
    wheel = synthetic.write_wheel(tmp_path / "dist")
    synthetic.write_sdist(tmp_path / "dist")
    synthetic.write_sdist(tmp_path / "dist", version="0.1.1")

    completed = _run_verification(tmp_path, wheel=wheel)

    assert completed.returncode != 0, "two sdists must fail the archive check"
    assert "exactly one source distribution" in completed.stderr


def test_the_verification_rejects_a_wheel_that_does_not_import(
    tmp_path: Path,
) -> None:
    """A wheel whose package is missing fails before either entry point runs."""
    wheel = synthetic.write_wheel(
        tmp_path / "dist", synthetic.WheelSpec(include_package=False)
    )

    completed = _run_verification(tmp_path, wheel=wheel)

    assert completed.returncode != 0, "the import must be checked"
    assert "No module named 'hecate'" in completed.stderr


def test_the_verification_rejects_a_failing_check_command(
    tmp_path: Path,
) -> None:
    """A ``hecate check`` that exits non-zero fails the installation step."""
    wheel = synthetic.write_wheel(tmp_path / "dist", synthetic.WheelSpec(check_exit=1))

    completed = _run_verification(tmp_path, wheel=wheel)

    assert completed.returncode != 0, "the check command's status must be checked"
    assert "hecate check --config" in completed.stderr


def test_the_verification_uses_python_3_14_and_an_outside_venv() -> None:
    """The clean environment is 3.14 and lives outside the checkout."""
    build = next(
        item
        for item in steps(WORKFLOW, JOB)
        if item.get("uses") == "./.github/actions/pure-python-wheel"
    )
    assert typ.cast("dict[str, str]", build["with"])["python-version"] == "3.14"

    verify = step(JOB, VERIFY_STEP, workflow=WORKFLOW)
    assert verify["env"] == {
        "WHEEL_DIR": "dist",
        "VENV_DIR": "${{ runner.temp }}/hecate-wheel-verify",
        "POLICY": "${{ github.workspace }}/tests/fixtures/installed_cli/policy.toml",
    }
    script = step_script(JOB, VERIFY_STEP, workflow=WORKFLOW)
    assert 'python3 -m venv "${VENV_DIR}"' in script
    assert "scripts/verify_installed_distribution.py" in script
