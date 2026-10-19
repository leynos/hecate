"""Cyclopts command-line interface."""

from __future__ import annotations

import dataclasses as dc
import enum
import sys
import typing as typ
from pathlib import Path

import cyclopts

from .checker import ArchitectureCheckResult, check_architecture
from .config import ConfigError, ConfigOverrides, load_config
from .imports import DiscoveryError
from .output import render_json, render_text
from .source import SourceError

if typ.TYPE_CHECKING:
    from .policy import ArchitecturePolicy


class OutputFormat(enum.StrEnum):
    """Supported output formats."""

    TEXT = "text"
    JSON = "json"


app = cyclopts.App(name="hecate", result_action=lambda value: value)


@cyclopts.Parameter(name="*")
@dc.dataclass(frozen=True, slots=True)
class _SourceArgs:
    """Source-selection arguments forwarded to ``load_config``."""

    config: Path | None = None
    package: str | None = None
    root: Path | None = None
    include_external_packages: bool | None = None
    strict: bool | None = None


@cyclopts.Parameter(name="*")
@dc.dataclass(frozen=True, slots=True)
class _OutputArgs:
    """Output-behaviour arguments for the check command."""

    output_format: typ.Annotated[OutputFormat, cyclopts.Parameter(name="--format")] = (
        OutputFormat.TEXT
    )
    show_ignored: bool = False
    show_coverage: bool = False
    fail_on_unmatched_ignore: bool = False
    fail_on_warnings: bool = False


_DEFAULT_SOURCE_ARGS = _SourceArgs()
_DEFAULT_OUTPUT_ARGS = _OutputArgs()


def _emit_check_output(
    result: ArchitectureCheckResult,
    out: _OutputArgs,
    *,
    policy: ArchitecturePolicy,
    passed: bool,
) -> None:
    """Render and print the architecture-check result to stdout.

    JSON always carries the coverage section, so machine consumers can see
    unclassified and unresolved edges without a second invocation. Text keeps
    coverage behind an explicit flag to preserve existing snapshot output.

    Unclassified-module diagnostics take neither route: the configured mode
    already asked for them, so both formats carry them whenever the mode is
    anything other than ``ignore``. That decision is read from ``policy``
    rather than passed separately, so a rendered run and an exit code can never
    disagree about which mode was in force.

    ``passed`` is the command outcome rather than ``result.ok``: a run failing
    on warnings has no violation, so rendering from the result would print a
    pass notice for a run that exits non-zero.
    """
    output = (
        render_json(
            result,
            show_ignored=out.show_ignored,
            show_coverage=True,
            include_unclassified=policy.unclassified_modules != "ignore",
            passed=passed,
        )
        if out.output_format is OutputFormat.JSON
        else render_text(
            result,
            show_ignored=out.show_ignored,
            show_coverage=out.show_coverage,
            passed=passed,
        )
    )
    print(output, end="")


@app.command
def check(
    src: _SourceArgs = _DEFAULT_SOURCE_ARGS,
    out: _OutputArgs = _DEFAULT_OUTPUT_ARGS,
) -> int:
    """Check configured Python packages for architecture violations.

    Parameters
    ----------
    src : _SourceArgs
        Source-selection arguments for configuration discovery and package
        overrides.
    out : _OutputArgs
        Output rendering and unmatched-ignore handling options.

    Returns
    -------
    int
        Process exit code for the check result.

    Raises
    ------
    Exception
        Unexpected failures from architecture checking are allowed to propagate.

    Exit codes
    ----------
    0
        The architecture check passed. Warnings, including unclassified-module
        diagnostics under ``unclassified_modules = "warn"``, do not change this
        code.
    1
        Architecture violations, or error-severity coverage findings, were
        found. ``unclassified_modules = "error"`` reaches this code through an
        unclassified module. ``--fail-on-warnings`` also reaches this code when
        warning-level edges were reported.
    2
        Configuration, command-line, or input validation failed. This includes
        a package root that could not be walked, a scanned source file that
        could not be read or parsed, and an unmatched ignore under
        ``--fail-on-unmatched-ignore``.
    """
    try:
        hecate_config = load_config(
            src.config,
            ConfigOverrides(
                package=src.package,
                root=src.root,
                include_external_packages=src.include_external_packages,
                strict=src.strict,
                show_ignored=out.show_ignored,
                show_coverage=out.show_coverage,
                fail_on_unmatched_ignore=out.fail_on_unmatched_ignore,
            ),
        )
        result = check_architecture(hecate_config)
    except (ConfigError, DiscoveryError, SourceError) as error:
        print(f"hecate: {error}", file=sys.stderr)
        return 2
    if out.fail_on_unmatched_ignore and result.unmatched_ignores:
        for unmatched_ignore in result.unmatched_ignores:
            print(f"hecate: unmatched ignore {unmatched_ignore}", file=sys.stderr)
        return 2
    # The outcome is decided before rendering so the output can never show a
    # pass notice for a run that exits non-zero. Warnings are still rendered,
    # so an enforced run names the edges it is failing on.
    warned_edges_fail = out.fail_on_warnings and bool(result.warnings)
    passed = result.ok and not warned_edges_fail
    _emit_check_output(result, out, policy=hecate_config.policy, passed=passed)
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    """Run the Cyclopts application.

    Parameters
    ----------
    argv : list[str] | None
        Command-line arguments to parse. When omitted, Cyclopts reads
        ``sys.argv``.

    Returns
    -------
    int
        Process exit code returned by the selected command.

    Exit codes
    ----------
    0
        The selected command completed successfully.
    1
        The selected command found architecture violations.
    2
        Cyclopts command-line parsing or configuration handling failed.

    Raises
    ------
    Exception
        Unexpected exceptions from command execution are allowed to propagate.
    """
    try:
        value = app(argv)
    except cyclopts.CycloptsError as error:
        print(error, file=sys.stderr)
        return 2
    return int(value or 0)
