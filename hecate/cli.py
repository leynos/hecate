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
from .output import render_json, render_text


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


@cyclopts.Parameter(name="*")
@dc.dataclass(frozen=True, slots=True)
class _OutputArgs:
    """Output-behaviour arguments for the check command."""

    output_format: typ.Annotated[OutputFormat, cyclopts.Parameter(name="--format")] = (
        OutputFormat.TEXT
    )
    show_ignored: bool = False
    fail_on_unmatched_ignore: bool = False


_DEFAULT_SOURCE_ARGS = _SourceArgs()
_DEFAULT_OUTPUT_ARGS = _OutputArgs()


def _emit_check_output(
    result: ArchitectureCheckResult,
    *,
    output_format: OutputFormat,
    show_ignored: bool,
) -> None:
    """Render and print the architecture-check result to stdout."""
    output = (
        render_json(result, show_ignored=show_ignored)
        if output_format is OutputFormat.JSON
        else render_text(result, show_ignored=show_ignored)
    )
    print(output, end="")


@app.command
def check(
    src: _SourceArgs = _DEFAULT_SOURCE_ARGS,
    out: _OutputArgs = _DEFAULT_OUTPUT_ARGS,
) -> int:
    """Check configured Python packages for architecture violations.

    Returns
    -------
    int
        Process exit code for the check result.

    Exit codes
    ----------
    0
        The architecture check passed.
    1
        Architecture violations were found.
    2
        Configuration, command-line, or input validation failed.
    """
    try:
        hecate_config = load_config(
            src.config,
            ConfigOverrides(
                package=src.package,
                root=src.root,
                include_external_packages=src.include_external_packages,
                show_ignored=out.show_ignored,
                fail_on_unmatched_ignore=out.fail_on_unmatched_ignore,
            ),
        )
        result = check_architecture(hecate_config)
    except ConfigError as error:
        print(f"hecate: {error}", file=sys.stderr)
        return 2
    if out.fail_on_unmatched_ignore and result.unmatched_ignores:
        for unmatched_ignore in result.unmatched_ignores:
            print(f"hecate: unmatched ignore {unmatched_ignore}", file=sys.stderr)
        return 2
    _emit_check_output(
        result, output_format=out.output_format, show_ignored=out.show_ignored
    )
    return 0 if result.ok else 1


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
