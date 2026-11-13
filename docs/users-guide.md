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

Exit code `0` means the package passed, including runs whose only findings are
warnings. Exit code `1` means Hecate found architecture violations, a finding
at error severity such as an unclassified module under
`unclassified_modules = "error"`, or the run passed `--fail-on-warnings` and
found warning-level edges. Exit code `2` means configuration, command-line
input, or package-root validation failed. `2` also covers a scanned source file
that Hecate could not read or parse: the file and the reason are reported on
standard error, so a broken checkout is never mistaken for an architecture
finding.

Configuration validation also rejects a prefix in a later group when an earlier
group's equal or broader prefix already claims it. The diagnostic names both
groups and prefixes and exits with code `2`. Move a narrower exception group
before the broader group, remove a dead prefix, or correct the group that
should own the prefix. Equal prefixes cannot be fixed by reordering; remove the
duplicate from one group.

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

## Unclassified-module reporting

Coverage reporting watches edges. A module no configured group claims is a
different gap: every import it makes or receives sits outside group-based
enforcement, so a package added without a matching prefix can drift unchecked
while each existing check still passes. `unclassified_modules` reports the
module itself:

```toml
[tool.hecate]
unclassified_modules = "error"
```

The setting accepts three values:

| Mode     | Behaviour                                                            |
| -------- | -------------------------------------------------------------------- |
| `ignore` | Report nothing. This is the default and preserves earlier output.    |
| `warn`   | Report each unclassified module as a warning; the exit code stays 0. |
| `error`  | Report each unclassified module as an error; the check exits 1.      |

A finding names the module and says why it was reported:

```plaintext
HEC002 error sample.newthing: no architecture group matched this module
```

Module findings carry the fixed rule identifier `HEC002`, so a consumer can
tell them apart from edge diagnostics, which use the configured
`default_rule_id`. For that reason `HEC002` is reserved: a configuration that
sets `default_rule_id = "HEC002"` is rejected as invalid.

### What counts as a discovered module

- Every `*.py` file beneath a configured package root, including `__init__.py`
  and files with no imports at all. A new package is reported on its first run,
  before it grows its first import.
- Classification reuses the ordered, first-match rule described under
  [group tables](configuration.md#group-tables). A dotted prefix matches at a
  boundary, so a group for `sample.domain` does not classify a lookalike
  `sample.domainx`.
- A package `__init__.py` is claimed when any configured prefix lies beneath
  it. An initializer imports and re-exports what its submodules bind, so groups
  for `sample.domain` already cover the `sample.domain` package without a
  recursive group for `sample`. That containment stops at the initializer:
  `sample.newthing` is a plain module and is still reported.
- External imports are not modules for this purpose. They continue to follow
  `include_external_packages` and the external prefixes groups declare.

### Reading the output

Text output shows module findings whenever the mode is `warn` or `error`,
because the configuration already asked for them. Under `warn` the pass notice
still appears, since warnings do not change the exit code:

```plaintext
hecate: architecture check passed
HEC002 warning sample.newthing: no architecture group matched this module
```

Under `error` there is no pass notice, and the exit code is `1`.

JSON output carries an `unclassified_modules` array in both reporting modes,
sorted by module name. The array is present and empty when the tree is fully
classified, which a consumer reads as "evaluated and clean" rather than as "not
reported":

```json
{
  "ok": false,
  "unclassified_modules": [
    {
      "message": "no architecture group matched this module",
      "module": "sample.newthing",
      "rule_id": "HEC002",
      "severity": "error",
      "source_path": "/repo/sample/newthing/__init__.py"
    }
  ]
}
```

Under `ignore` the key is absent entirely, so the default payload is unchanged.
The exit code follows from the findings: `warn` leaves it at `0`, `error` makes
it `1`.

A module finding does not change how the edges around that module are
classified. An import edge with an unclassified endpoint stays outside
group-based enforcement in all three modes; the finding exists to make that gap
visible. See [coverage reporting](#coverage-reporting) for how such edges are
reported by strict mode.

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
not have to be left undeclared during the migration. Naming it in a group's
`warn` list makes Hecate report the edges without failing the build:

```toml
[[tool.hecate.groups]]
name = "application"
prefixes = ["sample.application"]
allowed = ["application", "domain"]
warn = ["legacy"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["sample.domain"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "legacy"
prefixes = ["sample.legacy"]
allowed = ["legacy"]
```

Now every edge from `sample.application` to `sample.legacy` appears in the
output as a warning. The run stays green, and the direction is visible in CI
rather than being assumed:

```plaintext
HEC001 (warning): sample.application.service:1 imports warning-level module sample.legacy.old (application -> legacy)
```

Warnings are shown whether the run passes or fails, so a run that also has a
real violation reports both rather than hiding the warnings behind the failure.

`ok` in JSON output describes the architecture result alone, so it stays `true`
for a warning-only run even under `--fail-on-warnings`. The command outcome is
reported separately as `status`, which is `"failed"` whenever the process exits
non-zero. A consumer deciding whether the command succeeded should read
`status`; `ok` answers whether the package itself passed. JSON output always
carries a `warnings` array, empty when there is nothing to report, so a
consumer can read the key unconditionally:

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

## Duplication gate

`make lint` runs a blocking code-duplication gate, so a change that adds
duplication fails lint rather than merely being reported. The gate scans the
`hecate` package with the pinned `nose` detector; the repository's helper
scripts, tests, and documentation are out of scope. Its internals are in the
[developers' guide](developers-guide.md#duplication-gate).

Two targets cover the workflow:

- `make duplication` runs the gate on its own, outside `make lint`. It first
  runs `df12-duplication install`, which downloads the detector into
  `.tools/nose` and verifies it against a digest table shipped in the pinned
  `df12-python-lints` package; it is idempotent.
- `make duplication-allow` records a reasoned exception; see below.

The gate is the `df12-duplication` command from `df12-python-lints`, pinned by
commit in the Makefile (`DF12_PYTHON_LINTS_SHA`). The detector version lives
only in `[tool.nose]`. The gate refuses to run when the binary reports a
different version, and it never compiles one from source. To use a detector
provisioned elsewhere, set `NOSE_BIN`; a relative path resolves against the
repository root. The gate's own behaviour and tests live in
`df12-python-lints`, and CI runs it through the shared-actions
`df12-duplication` action.

The gate exits `0` for a clean or fully-allowed scan and `1` when unsuppressed
families remain. That status is what `make duplication` and `make lint` pass on
as a failed recipe, but Make exits with status `2` for any failed recipe, so a
shell that ran `make` cannot tell a `1` from a `2`. Read the printed
diagnostic, not the exit status, to distinguish blocking duplication from a
gate that could not form a verdict. On failure the gate prints the family
count, one line per family, and the `make duplication-allow` command that would
record an exception:

```plaintext
duplicate code: 1 unsuppressed family/families
  hecate/a.py:1-9 run ~ hecate/b.py:1-9 run (exact, value 12.5)
Extract the shared logic into one helper, or record a considered exception:
  make duplication-allow FIRST='<path[::name]>' [SECOND='<path[::name]>'] REASON='<why this stays>'
```

A successful run prints `duplication gate passed`, with the number of allowed
families appended when reasoned exceptions silenced anything. A stale entry is
reported on a successful run too, as
`stale allow entry (<keys>): unmatched in this scan`, followed by the advice to
widen the scan before deleting it.

Exit `2` means the gate could not produce a verdict, and the diagnostic is
prefixed with the class of failure. A missing detector, a version mismatch, a
failed detector run, a timeout, or a report that is not valid JSON prints an
`error:` line; `make duplication` installs the pinned detector again. An allow
entry that is readable but wrong, such as one with a missing reason, both
`unit` and `members` set, or a malformed location key, prints a
`configuration error:` line naming the offending entry. A `pyproject.toml` that
is missing or is not valid TOML also prints a `configuration error:` line
naming the file.

Genuine duplication should be extracted, not allow-listed; an exception asserts
that a parallel is intentional and reviewable. Record one with:

```bash
make duplication-allow FIRST='path[::name]' REASON='why this stays'
make duplication-allow FIRST='path[::name]' SECOND='path[::name]' REASON='why this stays'
```

`FIRST` names one location key and is required. Repeat `SECOND` for a family
with more members, adding one key per option with `SECOND=... SECOND+=...`.
`REASON` is required and is stored beside the entry. A key is a POSIX glob
`path` matching any location in a matching file, or `path::name`, which
additionally requires the detector's unit name. An entry silences a family only
when **every** location in it matches one of the entry's keys, so a new copy in
an unlisted file still blocks, and partial coverage from several entries never
adds up. The command runs the detector first and refuses a key set that covers
no reported family, so a misspelled key fails instead of recording an exception
that changes nothing.

An entry the current run cannot match is reported as stale, meaning **unmatched
in this scan** rather than proven gone. The scan is bounded by `top`, so a
family below the ranking is not reported at all and the gate cannot tell that
from a family that no longer exists. Widen the scan before deleting such an
entry: raise `top`, or lower `min-size`, and re-run.

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
