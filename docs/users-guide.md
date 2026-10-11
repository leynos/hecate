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

A warning-level edge has the same fields with an explicit severity:

```plaintext
HEC001 (warning): sample.application.service:1 imports warning-level module sample.legacy.old (application -> legacy)
```

Exit code `0` means the package passed. Exit code `1` means Hecate found
architecture violations, or the run passed `--fail-on-warnings` and found
warning-level edges. Exit code `2` means configuration, command-line input, or
package-root validation failed. `2` also covers a scanned source file that
Hecate could not read or parse: the file and the reason are reported on
standard error, so a broken checkout is never mistaken for an architecture
finding.

## Import outcome states

Hecate evaluates every in-scope import edge it finds and records exactly one
outcome. An edge is in scope when it lies within the scanned package roots, or
when it is external and the configuration puts it there: an external edge is in
scope only when `include_external_packages` is enabled and a configured group
claims its prefix. Any other external import is out of scope and receives no
outcome at all. A green result therefore means no edge was forbidden and no
coverage finding carried error severity, not that in-scope edges were quietly
skipped. The states are:

| State          | Meaning                                                                          |
| -------------- | -------------------------------------------------------------------------------- |
| `permitted`    | Both endpoints are classified, and the importer group may import the target.     |
| `forbidden`    | Both endpoints are classified, and the importer group may not import the target. |
| `warned`       | Both endpoints are classified, and the importer group tolerates the target.      |
| `exempted`     | Not permitted in principle, but covered by a documented `ignore_imports` entry.  |
| `unclassified` | At least one endpoint matched no configured group.                               |
| `unresolved`   | The import target resolved to no known internal module.                          |

`permitted` and `forbidden` edges are the normal case. The remaining states are
reported in different places:

- `unclassified` and `unresolved` appear in the **coverage** section described
  below, and fail the check only under the conditions given there;
- `warned` appears in the **warnings** section, which is always present and
  never fails the check by itself; and
- `exempted` appears in the **ignored** section, which text output shows only
  when `--show-ignored` is passed.

An edge that matches an `ignore_imports` entry is recorded as `exempted`, so it
is reported as ignored and *not* as coverage. A documented ignore is therefore
the way to accept a known `unclassified` or `unresolved` edge without the
coverage section reporting it.

## Coverage reporting

Unclassified and unresolved edges are reported rather than skipped, so a new
package subtree or a misspelled prefix in the policy always leaves a trace
instead of vanishing. Whether that trace fails the build depends on severity:
only an entry at `error` severity sets a non-zero exit code.

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
edge, because that is what Python does. A name `__all__` selects but the module
never binds still counts as exported, and is reported as unresolved, because
the star import raises `AttributeError` when it runs.

When a module binds one name more than once, Hecate reports every origin the
name may hold. A binding written unconditionally runs on every import and
supersedes earlier candidates; a binding inside an `if`, `try`, or loop body
may not run, so it adds an origin instead of replacing one.

Where `__all__` is absent or non-literal, the default public-name rule applies.
Star exports are expanded when the origin module can be resolved statically. A
wildcard whose export set cannot be resolved is reported as unresolved instead
of being approximated away.

## Migrating with warning-level directions

A dependency that should eventually be forbidden, but is still widespread, does
not have to be left undeclared while you work through it. Naming it in a group's
`warn` list makes Hecate report the edges without failing the build:

```toml
[[tool.hecate.groups]]
name = "application"
prefixes = ["sample.application"]
allowed = ["application", "domain"]
warn = ["legacy"]
```

Now every edge from `sample.application` to `sample.legacy` appears in the
output as a warning. The run stays green, and the direction is visible in CI
rather than being assumed:

```plaintext
HEC001 (warning): sample.application.service:1 imports warning-level module sample.legacy.old (application -> legacy)
```

Warnings are shown whether the run passes or fails, so a run that also has a
real violation reports both rather than hiding the warnings behind the failure.
JSON output always carries a `warnings` array, empty when there is nothing to
report, so a consumer can read the key unconditionally:

```bash
hecate check --format json | jq '.warnings'
```

A warning is not a permission to ignore. Once the migration is finished, move
the target from `warn` to `allowed` to make it silent, or delete the entry to
make it forbidden again. Listing a target in both `allowed` and `warn` is a
configuration error, so the two states cannot drift into each other by accident.

To stop the migration from standing still, make warning-level edges fail:

```bash
hecate check --fail-on-warnings
```

That run exits `1` when any warned edge was reported, after printing the
diagnostics, so a pipeline fails on the same output a developer sees. Use it
once the toleration is meant to be temporary and every new warning should be
dealt with as it appears.

Warning targets follow the same rule as `allowed`: they must name declared
groups. A `warn` list that names an undeclared group exits `2` with the
offending groups reported, because such an entry can never match anything and
would read as a migration that is not in place.

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
