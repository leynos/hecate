# Hecate migration notes

These notes record the user-facing changes in the next pre-1.0 minor release,
relative to 0.1.0. The release introduces coverage reporting, strict mode, and
warning-level dependency directions in `hecate check`, and corrects re-export
and `__all__` semantics. Projects already running `hecate check` should read
this document before refreshing a policy or a gate that consumes Hecate output.

## Coverage reporting

Every in-scope import edge receives exactly one of five outcomes: `permitted`,
`forbidden`, `exempted`, `unclassified`, or `unresolved`. An edge whose
importer or target endpoint matched no configured group is `unclassified`, and
a target that names no known internal module is `unresolved`. Those two states
are reported in the **coverage** section rather than skipped, so a new package
subtree or a misspelled prefix leaves a trace instead of vanishing.

Outside strict mode a coverage finding is a warning that does not change the
exit code. Inside strict mode it fails the check. A green result therefore
means no edge was forbidden and no coverage finding carried error severity,
rather than that in-scope edges passed unexamined.

Text output hides coverage warnings by default to keep snapshots stable. Pass
`--show-coverage` to include them alongside a pass or fail message; coverage
findings that fail the check are always shown. An edge is in scope when it lies
within the scanned package roots, or when it is external and the configuration
brings it into scope (see [External edges](#external-edges)).

## New command-line options

The new `hecate check` options are:

- `--strict` and `--no-strict` override the configured `strict` value for a
  single run.
- `--show-coverage` adds coverage warnings to text output; JSON always
  carries them.
- `--fail-on-warnings` exits `1` when warning-level edges were reported; see
  [Warning-level dependency directions](#warning-level-dependency-directions).

## External edges

An external import is in scope only when `include_external_packages` is enabled
*and* a configured group claims its prefix. Any other external import is out of
scope and receives no outcome at all.

The option widens what *can* be classified; it does not assert that every
third-party import was classified. A claimed prefix such as `sqlalchemy` is
enforced, while an unclaimed dependency such as `json` is skipped, so enabling
external classification never turns a third-party dependency into a failure by
itself.

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

`--strict` and `--no-strict` override the configured value for one run, so a
strict project can be inspected without editing its configuration.

Under strict mode:

- an unclassified internal edge always fails the check;
- an unresolved internal edge fails too, unless
  `unresolved_internal_severity` lowers it to `warning` or `exempt`; and
- documented `ignore_imports` entries still exempt the edges they cover.

Strict mode applies to edges within the scanned package roots. `strict`
defaults to `false`, so an existing policy keeps its current exit code until
strict mode is enabled.

## JSON coverage output

JSON output always includes a `coverage` array, regardless of
`--show-coverage`, so a machine consumer needs only one invocation:

```bash
hecate check --format json | jq '.coverage'
```

Each entry carries `state`, `severity`, `importer`, `imported`, `line`, and
whichever endpoint groups were resolved. Update JSON consumers to read the new
`coverage` array; consumers that ignore unknown keys need no change. An entry
with `error` severity is the reason a run failed.

## Ignoring incomplete edges

An `ignore_imports` entry covers incomplete edges as well as forbidden ones. A
matched edge is recorded as `exempted`, so it is reported as ignored and not as
coverage. A documented ignore is therefore the supported way to accept a known
`unclassified` or `unresolved` edge.

```toml
[[tool.hecate.ignore_imports]]
importer = "beatcue.config"
imported = "beatcue.adapters.outbound"
reason = "Composition root wiring."
```

Ignores match dotted descendants: an ignore for `sample.config` importing
`sample.adapters.outbound` also covers `sample.config.runtime` importing
`sample.adapters.outbound.db`. Every ignore needs a non-empty reason, and
`--fail-on-unmatched-ignore` fails the run when an entry exempts no edge. The
ignored section itself is shown when `--show-ignored` is passed.

## Unclassified-module reporting

Coverage reporting watches edges. A module no configured group claims is a
related but separate gap: every import it makes or receives sits outside
group-based enforcement, so a package added without a matching prefix can drift
unchecked while every edge check still passes.

`unclassified_modules` reports the module itself:

```toml
[tool.hecate]
unclassified_modules = "error"
```

The mode is one of `ignore`, `warn`, or `error`:

- `ignore` is the default and preserves earlier behaviour. The module pass runs
  but asks no classification question and records nothing, and the JSON payload
  is unchanged.
- `warn` records each unclaimed module as a warning without changing the exit
  code.
- `error` records each unclaimed module as an error and fails the check with
  exit code 1.

Module findings carry the fixed rule identifier `HEC002`, so a consumer can
tell them apart from edge diagnostics, which use the configured
`default_rule_id`. `HEC002` is therefore reserved: a configuration that sets
`default_rule_id = "HEC002"` is rejected, so the two kinds of diagnostic cannot
become indistinguishable.

Discovery covers every `*.py` file beneath a configured package root, including
`__init__.py` and files with no imports, so a new package is reported on its
first run. A package initializer is claimed when any configured prefix lies
beneath it, because it re-exports what its submodules bind; specific groups
such as `sample.domain` therefore cover the `sample.domain` package without a
recursive group for `sample`. Plain modules get no containment, so
`sample.newthing` is still reported.

JSON output carries an `unclassified_modules` array under `warn` and `error`,
sorted by module name, and the array is present and empty when the tree is
fully classified. Under `ignore` the key is absent. Text output shows module
findings only under `warn` and `error`.

## Re-export and `__all__` semantics

Re-export origins are corrected in this release. Hecate keeps two views of
every module, matching Python's own rules:

- the names a module **binds**, which is what `from module import name`
  reaches; and
- the names a module **exports to wildcards**, which `__all__` governs.

`__all__` selects wildcard exports only. It never removes a binding, so an
explicitly imported re-export keeps its origin even when `__all__` omits it or
is set to `[]`. A wildcard over `__all__ = []` binds nothing beyond the module
edge, because that is what Python does. A name `__all__` selects but the module
never binds still counts as exported and is reported as unresolved, because the
star import raises `AttributeError` when it runs.

Re-export chains are followed through every hop, and star exports are expanded
when the origin module can be resolved statically. A wildcard whose export set
cannot be resolved is reported as unresolved rather than approximated away.
When a module binds one name more than once, every origin the name may hold is
reported: an unconditional binding supersedes earlier candidates, while one
inside an `if`, `try`, or loop body adds an origin instead of replacing one.

A boundary violation can no longer hide behind a barrel that re-exports a
forbidden module explicitly while omitting it from `__all__`.

## Warning-level dependency directions

A group may name a target in a new `warn` list. Edges in that direction are
reported without failing the run, which lets a migration declare a dependency
it intends to remove instead of leaving it undeclared:

```toml
[[tool.hecate.groups]]
name = "application"
prefixes = ["sample.application"]
allowed = ["application", "domain"]
warn = ["legacy"]

[[tool.hecate.groups]]
name = "legacy"
prefixes = ["sample.legacy"]
allowed = ["legacy"]
```

Each warned edge is printed with `(warning)` in place of a violation's rule
prefix, so the direction is visible on a green run:

```plaintext
HEC001 (warning): sample.application.service:1 imports warning-level module sample.legacy.old (application -> legacy)
```

Warnings do not change the exit code by default: a run whose only findings are
warned edges still exits `0`. Warnings are also rendered beside violations, so
a run that fails for a real violation still names the warned edges it found.

`--fail-on-warnings` makes the run exit `1` when any warned edge was reported,
after printing the diagnostics. Enforcement applies to every warned edge in the
current run, not only to one that first appears after the flag is added: if the
policy already reports a warned edge, enabling the flag exits `1` immediately.
Use it once a toleration is meant to be temporary; it turns the warning list
into a ratchet that fails while any warned edge remains.

Edges in a warned direction are classified before the violation check, so a
group that warns one target still forbids every target it does not allow.
Precedence is unchanged for everything else: an allowed direction is silent
before `ignore_imports` is consulted, and a documented ignore suppresses a
warned edge exactly as it suppresses a violation.

### Warning output

Text output always shows warnings, on passing and failing runs alike. JSON
output always carries a `warnings` array, empty when there is nothing to
report, so a consumer can read the key unconditionally. Each entry carries
`state: "warned"`, `severity: "warning"`, and the same identity fields as a
violation.

JSON also carries a `status` field. `ok` still describes the architecture
result alone, so it remains `true` for a warning-only run even under
`--fail-on-warnings`; `status` reports the command outcome and is `"failed"`
whenever the process exits non-zero. A consumer deciding whether the command
succeeded should read `status`, while `ok` answers whether the package itself
passed. Consumers that ignore unknown keys need no change.

### Warning validation

Warning targets follow the same rule as `allowed`: they must name declared
groups. Configuration loading rejects, and `hecate check` exits `2` for:

- a `warn` value that is not a list of non-blank strings;
- a warning target that no group declares; and
- a target listed in both `allowed` and `warn`, which would make the outcome
  depend on the order the checks run in.

## Shadowed group prefixes

Configuration loading now rejects a later group's prefix when an earlier
group's equal or dotted-ancestor prefix makes it unreachable under ordered
matching. `hecate check` reports the configuration error and exits with code 2,
even when strict mode is disabled. For a broad-before-narrow overlap, move the
narrower group earlier, remove the unreachable prefix, or correct the group
that owns the prefix. For equal prefixes in different groups, remove one
duplicate or correct its group ownership; reordering cannot resolve the
conflict while both groups retain the prefix.

## Migration checklist

1. Re-run `hecate check` after upgrading. A non-strict run keeps its current
   exit code except that shadowed group prefixes now fail configuration loading
   with exit code 2, even without strict mode, and the corrected origin model
   may surface a violation that the previous model hid.
2. Review coverage with `hecate check --show-coverage`, and fix a missing
   group prefix or package subtree rather than suppressing the finding.
3. Adopt strict mode deliberately: set `strict = true` in `[tool.hecate]`, or
   trial it with `--strict` and `--no-strict` before committing to it.
4. While a known-unresolved edge awaits cleanup, set
   `unresolved_internal_severity = "warning"` so the edge stays visible without
   failing the build.
5. Document accepted unclassified or unresolved edges as
   `[[tool.hecate.ignore_imports]]` entries with reasons, and use
   `--fail-on-unmatched-ignore` to catch entries that exempt no edge.
6. Update JSON consumers to read the new `coverage` array.
7. Re-check package barrels: an explicit re-export keeps its origin when
   `__all__` omits it, so a finding there reflects the import Python performs.
8. Enable `include_external_packages` only where groups claim the external
   prefixes that should be enforced; unclaimed prefixes stay skipped.
9. Decide whether to enforce module coverage. The default `ignore` is
   backwards compatible, so this is opt-in. Trial
   `unclassified_modules = "warn"` to surface packages no group claims, then
   switch to `"error"` once the policy covers the tree. Do not set
   `default_rule_id = "HEC002"`, which is reserved for module findings.
10. Record dependencies planned for removal in a group's `warn` list. The run
    stays green, and every edge in that direction is reported until the list
    is emptied.
11. Update JSON consumers that decide success from `ok` alone. Warnings do not
    affect `ok`, so a warning-only run under `--fail-on-warnings` reports
    `ok: true` beside `status: "failed"`.
12. Once a migration is complete, move the target from `warn` to `allowed` to
    make it silent, or delete the entry to make it forbidden again. Adopt
    `--fail-on-warnings` when the toleration is meant to be temporary.
