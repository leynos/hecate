# Hecate users' guide

Hecate checks Python package imports against a TOML architecture policy. It is
intended for projects that use hexagonal architecture and need CI-stable
diagnostics for dependency-direction drift.

## Running checks

Run Hecate from the project root:

```bash
hecate check
```

The command discovers `[tool.hecate]` in `pyproject.toml`. To use another TOML
file, pass `--config`:

```bash
hecate check --config architecture.toml
```

Use JSON output for machine consumers:

```bash
hecate check --format json
```

Text output is deterministic and suitable for snapshot tests.

## Reading diagnostics

A violation has this shape:

```plaintext
HEC001: sample.domain.model:1 imports forbidden module sample.adapters.db (domain -> adapter)
```

The fields are:

- rule identifier;
- importing module and source line;
- imported module;
- importing group and imported group.

Exit code `0` means the package passed. Exit code `1` means Hecate found
architecture violations. Exit code `2` means configuration, command-line input,
or package-root validation failed.

## Import outcome states

Hecate evaluates every import edge it finds and records exactly one outcome. A
green result therefore means each edge was understood and permitted, not that
some edges were quietly skipped. The states are:

| State          | Meaning                                                                          |
| -------------- | -------------------------------------------------------------------------------- |
| `permitted`    | Both endpoints are classified, and the importer group may import the target.     |
| `forbidden`    | Both endpoints are classified, and the importer group may not import the target. |
| `exempted`     | Forbidden in principle, but covered by a documented `ignore_imports` entry.      |
| `unclassified` | At least one endpoint matched no configured group.                               |
| `unresolved`   | The import target resolved to no known internal module.                          |

`permitted` and `forbidden` edges are the normal case. The remaining three are
reported in two different places:

- `unclassified` and `unresolved` appear in the **coverage** section described
  below, and fail the check only under the conditions given there; and
- `exempted` appears in the **ignored** section, which text output shows only
  when `--show-ignored` is passed.

An edge that matches an `ignore_imports` entry is recorded as `exempted`, so it
is reported as ignored and *not* as coverage. A documented ignore is therefore
the way to accept a known `unclassified` or `unresolved` edge without the
coverage section reporting it.

## Coverage reporting

Unclassified and unresolved edges are reported rather than skipped, so a new
package subtree or a misspelled prefix in the policy cannot silently produce a
green result.

JSON output always includes a `coverage` array:

```bash
hecate check --format json | jq '.coverage'
```

Each entry carries `state`, `severity`, `importer`, `imported`, `line`, and
whichever endpoint groups were resolved. Text output hides coverage warnings by
default to keep snapshots stable; pass `--show-coverage` to see them alongside
a pass or fail message. Coverage findings that fail the check are always shown.

An edge covered by a matching `ignore_imports` entry is exempted rather than
reported, so it appears in the ignored section and not in coverage. Only an
`unclassified` or `unresolved` edge with no matching ignore reaches the
coverage section.

Outside strict mode these findings are warnings, so adding a subtree does not
break an existing build. Inside strict mode they become failures.

## Strict mode

Strict mode rejects architectural blind spots. Enable it in configuration:

```toml
[tool.hecate]
strict = true
```

or for a single run:

```bash
hecate check --strict
```

In strict mode an unclassified internal edge always fails. An unresolved
internal edge also fails unless configured otherwise:

```toml
[tool.hecate]
strict = true
unresolved_internal_severity = "warning"
```

The severity accepts `error`, `warning`, or `exempt`. Use the warning setting
while a known-unresolved edge awaits cleanup, so the edge stays visible without
failing the build.

## Re-export handling

Package barrels do not hide forbidden imports. Hecate keeps two views of every
module, matching Python's own rules:

- the names a module **binds**, which is what `from module import name`
  reaches; and
- the names a module **exports to wildcards**, which `__all__` governs.

`__all__` selects wildcard exports only. It never removes a binding, so an
explicitly imported re-export keeps its origin even when `__all__` omits it or
is set to `[]`. A wildcard over `__all__ = []` binds nothing beyond the module
edge, because that is what Python does.

Where `__all__` is absent or non-literal, the default public-name rule applies.
Star exports are expanded when the origin module can be resolved statically. A
wildcard whose export set cannot be resolved is reported as unresolved instead
of being approximated away.

## Local validation

Run the full local gate before publishing changes:

```bash
make check-fmt
make lint
make typecheck
make test
make crosshair
```

`make crosshair` analyses only bounded pure helper contracts. It intentionally
does not analyse filesystem traversal, `ast.parse`, TOML parsing, or the CLI.
