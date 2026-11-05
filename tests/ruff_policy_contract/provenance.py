"""Read the files that say which Ruff the gate runs and how it is built.

A rule inventory is only meaningful against a named binary, and a policy that
can be re-resolved at install time is not a policy. These readers answer the
questions the provenance contract asks: what version ``uv.lock`` pins, and
what recipe ``make build`` runs to install it. Both are read as text rather
than trusted as convention, so a Makefile edit that drops the lockfile pin
fails a test instead of quietly re-resolving.
"""

from __future__ import annotations

import re
import tomllib

from .reading import REPO_ROOT, RuffPolicyError


def locked_ruff_version(lock_text: str) -> str:
    """Return the Ruff version ``uv.lock`` pins.

    Parameters
    ----------
    lock_text : str
        The lockfile source to read.

    Returns
    -------
    str
        The single version recorded for the ``ruff`` package.

    Raises
    ------
    RuffPolicyError
        If the lockfile has no ``ruff`` package entry or more than one. Two
        entries mean the lock is not the flat single-environment lock this
        test understands, and picking either would assert against a version
        the resolver may not install.

    """
    document = tomllib.loads(lock_text)
    packages = document.get("package", [])
    if not isinstance(packages, list):
        message = "uv.lock has no package list"
        raise RuffPolicyError(message)
    versions = [
        package.get("version")
        for package in packages
        if isinstance(package, dict) and package.get("name") == "ruff"
    ]
    if len(versions) != 1 or not isinstance(versions[0], str):
        message = f"uv.lock must pin exactly one ruff version, got {versions!r}"
        raise RuffPolicyError(message)
    return versions[0]


def lock_text() -> str:
    """Return the committed ``uv.lock`` source.

    Returns
    -------
    str
        The lockfile's text, unwritten by this reader.

    """
    return (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")


def makefile_text() -> str:
    """Return the Makefile source.

    Returns
    -------
    str
        The Makefile's text, which the goals are read out of.

    """
    return (REPO_ROOT / "Makefile").read_text(encoding="utf-8")


def goal_body(goal: str) -> str:
    """Return a Makefile goal's recipe with continuations joined.

    Parameters
    ----------
    goal : str
        The goal's name, as written before the colon.

    Returns
    -------
    str
        The recipe as one line of whitespace-separated words, so a command
        split across continuations can be matched as a single string.

    Raises
    ------
    RuffPolicyError
        If the Makefile declares no recipe for the goal.

    """
    match = re.search(
        rf"^{re.escape(goal)}:.*?\n((?:[ \t].*\n|[ \t].*)+)",
        makefile_text(),
        flags=re.MULTILINE,
    )
    if match is None:
        message = f"{goal} has no recipe in the Makefile"
        raise RuffPolicyError(message)
    return " ".join(match.group(1).replace("\\\n", " ").split())
