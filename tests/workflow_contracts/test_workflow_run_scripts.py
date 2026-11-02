"""Contracts over every ``run`` script the repository's CI ships.

A value pasted into a shell script with ``${{ }}`` is expanded before Bash sees
it, so a branch name or a matrix value can become shell syntax. Every value
must therefore reach the script through ``env:``. The sweep here reads every
workflow and composite action, including the release pipeline's, and admits
exactly one reviewed exception.
"""

from __future__ import annotations

import typing as typ

import pytest

from .ci_workflows import ROOT, jobs, parse_document, workflow_sources
from .release_workflow import WORKFLOW

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import pathlib as pth

#: The `id` of the publisher step that reports whether the CodeScene token
#: exists, and that step's whole command.
CREDENTIAL_CHECK_ID: typ.Final = "codescene-token"
CREDENTIAL_CHECK_COMMAND: typ.Final = (
    'echo "available=${{ secrets.CS_ACCESS_TOKEN != \'\' }}" >> "$GITHUB_OUTPUT"'
)

#: The one reviewed template expansion inside a shell script. It renders only
#: `true` or `false`, and the shared CV-005 contract (`token.check-step`)
#: requires the secret to be read there rather than through an `env` value.
_ALLOWED_EXPANSIONS: typ.Final = frozenset({
    ("coverage-main.yml", CREDENTIAL_CHECK_ID, CREDENTIAL_CHECK_COMMAND)
})


def _run_scripts(
    document: object, where: str
) -> cabc.Iterator[tuple[str, dict[str, object]]]:
    """Yield every mapping that declares a ``run`` script, with its location."""
    if isinstance(document, dict):
        if isinstance(document.get("run"), str):
            yield where, typ.cast("dict[str, object]", document)
        for key, value in document.items():
            yield from _run_scripts(value, f"{where}.{key}")
    elif isinstance(document, list):
        for index, value in enumerate(document):
            yield from _run_scripts(value, f"{where}[{index}]")


def _expansions_in(name: str, document: object) -> list[str]:
    """Return each ``run`` script location in ``document`` that expands ``${{``."""
    return [
        where
        for where, holder in _run_scripts(document, name)
        if "${{" in typ.cast("str", holder["run"])
        and (name, holder.get("id"), typ.cast("str", holder["run"]).strip())
        not in _ALLOWED_EXPANSIONS
    ]


def _document_name(path: pth.Path) -> str:
    """Name a workflow by file name and a composite action by its path."""
    if path.parent.name == "workflows":
        return path.name
    return path.relative_to(ROOT).as_posix()


def _ci_documents() -> dict[str, object]:
    """Parse every workflow and composite action in the repository.

    GitHub accepts both ``.yml`` and ``.yaml`` for each, so a sweep that read
    one extension would leave the other unchecked.
    """
    workflows, actions = ROOT / ".github" / "workflows", ROOT / ".github" / "actions"
    paths = [
        *sorted((*workflows.glob("*.yml"), *workflows.glob("*.yaml"))),
        *sorted((*actions.glob("*/action.yml"), *actions.glob("*/action.yaml"))),
    ]
    return {
        _document_name(path): parse_document(
            path.read_text(encoding="utf-8"), path.name
        )
        for path in paths
    }


def test_no_run_script_expands_a_template_expression() -> None:
    """Values reach a shell through ``env``, never by pasting into the script."""
    documents = _ci_documents()
    scanned = sum(
        len(list(_run_scripts(document, name))) for name, document in documents.items()
    )
    assert scanned > 20, "the scan must reach the repository's run scripts"
    assert ".github/actions/pure-python-wheel/action.yml" in documents
    findings = [
        where
        for name, document in documents.items()
        for where in _expansions_in(name, document)
    ]
    assert not findings, f"route these values through env: {findings}"


@pytest.mark.parametrize(
    ("name", "document", "is_flagged"),
    [
        ("x.yml", {"steps": [{"run": 'echo "${{ inputs.target }}"'}]}, True),
        ("x.yml", {"runs": {"steps": [{"run": "make ${{ matrix.check }}"}]}}, True),
        (
            "x.yml",
            {"steps": [{"env": {"T": "${{ inputs.t }}"}, "run": 'echo "$T"'}]},
            False,
        ),
        (
            "x.yml",
            {"steps": [{"id": CREDENTIAL_CHECK_ID, "run": CREDENTIAL_CHECK_COMMAND}]},
            True,
        ),
        (
            "coverage-main.yml",
            {"steps": [{"id": CREDENTIAL_CHECK_ID, "run": CREDENTIAL_CHECK_COMMAND}]},
            False,
        ),
    ],
    ids=[
        "input",
        "composite-matrix",
        "through-env",
        "exception-elsewhere",
        "exception",
    ],
)
def test_the_expansion_scan_discriminates(
    name: str, document: object, *, is_flagged: bool
) -> None:
    """The scan flags pasted values and admits only the one reviewed exception."""
    assert bool(_expansions_in(name, document)) is is_flagged


def _run_holders(document: object) -> list[int]:
    """Return the identity of every mapping with a string ``run``, iteratively."""
    found: list[int] = []
    pending = [document]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            if isinstance(node.get("run"), str):
                found.append(id(node))
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return found


@pytest.mark.parametrize(
    "document",
    [
        {"run": "echo hi"},
        {"steps": [{"run": "echo hi"}, {"uses": "actions/checkout@x"}]},
        {"steps": [{"run": 1, "with": {"run": "nested but not a script"}}]},
        [{"run": "a"}, {"steps": [{"run": "b"}]}],
        {"runs": {"steps": [{"run": "composite"}]}},
        {"steps": [{"run": "first"}, {"run": "second"}]},
        {"run": "parent", "branches": [{"run": "child"}]},
    ],
    ids=[
        "top-level",
        "one-of-two-steps",
        "non-string-run",
        "list-root",
        "nested-mapping-without-steps-key",
        "two-holders",
        "holder-inside-a-holder",
    ],
)
def test_the_run_script_scan_finds_exactly_the_run_holders(document: object) -> None:
    """The scan yields every mapping with a string ``run`` and nothing else."""
    scanned = list(_run_scripts(document, "doc"))

    assert sorted(id(holder) for _, holder in scanned) == sorted(
        _run_holders(document)
    ), "a missed holder is a script the expansion scan never reads"
    locations = [where for where, _ in scanned]
    assert len(set(locations)) == len(locations), "each holder has one location"


def test_nothing_is_ever_overwritten_and_pypi_holds_no_github_token() -> None:
    """No script clobbers an asset, and the PyPI job cannot touch GitHub."""
    scripts = [
        holder["run"]
        for name, document in _ci_documents().items()
        for _, holder in _run_scripts(document, name)
    ]
    assert scripts, "the scan must reach the repository's release scripts"
    assert not any("--clobber" in str(script) for script in scripts)
    assert "GH_TOKEN" not in str(jobs(WORKFLOW)["publish-pypi"]), (
        "the job holding the PyPI token must not also hold a GitHub token"
    )


def test_every_workflow_parses_without_duplicate_keys() -> None:
    """Every workflow the repository ships is a document YAML reads once."""
    sources = workflow_sources()
    assert sources, "the sweep must reach the repository's workflows"
    for name, text in sources:
        parse_document(text, name)
