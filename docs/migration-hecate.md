# Hecate migration notes

These notes record the user-facing changes in the next pre-1.0 minor release,
relative to 0.1.0. The release introduces coverage reporting and strict mode in
`hecate check`, and corrects re-export and `__all__` semantics. Projects
already running `hecate check` should read this document before refreshing a
policy or a gate that consumes Hecate output.

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

## Migration checklist

1. Re-run `hecate check` after upgrading. A non-strict run keeps its current
   exit code, except where the corrected origin model surfaces a violation that
   the previous model hid.
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
