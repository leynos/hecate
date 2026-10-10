"""Reading and parsing scanned Python source.

Scanning a package walks the filesystem and parses whatever it finds, so both
steps can fail on input that is not architecture: a path the process cannot
read, bytes that are not UTF-8, or text that is not valid Python. ``ast.parse``
and ``Path.read_text`` raise unrelated exception types for those cases, and
letting them escape turns a fixable input problem into a traceback.

This module is the one place that boundary is crossed, so every scanner reports
the same :class:`SourceError` and the CLI can exit with its documented
validation code.
"""

from __future__ import annotations

import ast
import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path


class SourceError(ValueError):
    """Raised when a scanned source file cannot be read or parsed."""


def parse_source(source_path: Path) -> ast.Module:
    """Parse ``source_path`` into an AST, or raise :class:`SourceError`.

    Parameters
    ----------
    source_path : Path
        File to read and parse. The path is included in any error, because the
        caller only has a dotted module name once this succeeds.

    Returns
    -------
    ast.Module
        The parsed module.

    Raises
    ------
    SourceError
        The file could not be read as UTF-8 text, or was not valid Python.
    """
    try:
        text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        msg = f"{source_path}: cannot read source: {error}"
        raise SourceError(msg) from error
    try:
        return ast.parse(text, filename=str(source_path))
    except SyntaxError as error:
        msg = f"{source_path}:{error.lineno}: invalid syntax: {error.msg}"
        raise SourceError(msg) from error
