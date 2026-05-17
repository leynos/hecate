"""Cyclopts command-line interface."""
# pylint: disable=too-many-arguments

from __future__ import annotations

import enum
import sys
from pathlib import Path

import cyclopts

from .checker import check_architecture
from .config import ConfigError, load_config
from .output import render_json, render_text


class OutputFormat(enum.StrEnum):
    """Supported output formats."""

    TEXT = "text"
    JSON = "json"


app = cyclopts.App(name="hecate", result_action=lambda value: value)


@app.command
def check(
    *,
    config: Path | None = None,
    package: str | None = None,
    root: Path | None = None,
    format: OutputFormat = OutputFormat.TEXT,
    include_external_packages: bool | None = None,
    show_ignored: bool = False,
    fail_on_unmatched_ignore: bool = False,
) -> int:
    """Check configured Python packages for architecture violations.

    Parameters
    ----------
    config : Path | None
        Explicit TOML configuration file. When omitted, Hecate discovers the
        nearest ``pyproject.toml`` containing ``[tool.hecate]``.
    package : str | None
        Package name override used with ``root``.
    root : Path | None
        Package root override used with ``package``.
    format : OutputFormat
        Diagnostic output format.
    include_external_packages : bool | None
        Override for whether classified external package imports are checked.
    show_ignored : bool
        Include diagnostics for imports suppressed by ignore entries.
    fail_on_unmatched_ignore : bool
        Return a configuration error when an ignore entry suppresses no
        violation.

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

    Raises
    ------
    ConfigError
        Caught internally and returned as exit code 2.
    Exception
        Unexpected exceptions from filesystem access, parsing, or rendering are
        allowed to propagate.
    """
    try:
        hecate_config = load_config(
            config,
            package=package,
            root=root,
            include_external_packages=include_external_packages,
            show_ignored=show_ignored,
            fail_on_unmatched_ignore=fail_on_unmatched_ignore,
        )
        result = check_architecture(hecate_config)
    except ConfigError as error:
        print(f"hecate: {error}", file=sys.stderr)
        return 2
    if fail_on_unmatched_ignore and result.unmatched_ignores:
        for unmatched_ignore in result.unmatched_ignores:
            print(f"hecate: unmatched ignore {unmatched_ignore}", file=sys.stderr)
        return 2
    output = (
        render_json(result, show_ignored=show_ignored)
        if format is OutputFormat.JSON
        else render_text(result, show_ignored=show_ignored)
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
