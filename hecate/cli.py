"""Cyclopts command-line interface."""

from __future__ import annotations

import dataclasses as dc
import enum
import sys
from pathlib import Path

import cyclopts

from .checker import check_architecture
from .config import ConfigError, ConfigOverrides, load_config
from .output import render_json, render_text


class OutputFormat(enum.StrEnum):
    """Supported output formats."""

    TEXT = "text"
    JSON = "json"


app = cyclopts.App(name="hecate", result_action=lambda value: value)


@cyclopts.Parameter(name="*")
@dc.dataclass
class _SourceArgs:
    """Source-selection arguments forwarded to ``load_config``."""

    config: Path | None = None
    package: str | None = None
    root: Path | None = None
    include_external_packages: bool | None = None


@cyclopts.Parameter(name="*")
@dc.dataclass
class _OutputArgs:
    """Output-behaviour arguments for the check command."""

    format: OutputFormat = OutputFormat.TEXT
    show_ignored: bool = False
    fail_on_unmatched_ignore: bool = False


_DEFAULT_SOURCE_ARGS = _SourceArgs()
_DEFAULT_OUTPUT_ARGS = _OutputArgs()


@app.command
def check(
    src: _SourceArgs = _DEFAULT_SOURCE_ARGS,
    out: _OutputArgs = _DEFAULT_OUTPUT_ARGS,
) -> int:
    """Check configured Python packages for architecture violations."""
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
    output = (
        render_json(result, show_ignored=out.show_ignored)
        if out.format is OutputFormat.JSON
        else render_text(result, show_ignored=out.show_ignored)
    )
    print(output, end="")
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
