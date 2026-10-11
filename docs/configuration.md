# Hecate configuration

Hecate reads TOML configuration from `[tool.hecate]` in `pyproject.toml` by
default. The `--config PATH` option loads another TOML file with the same table
shape. Relative package roots are resolved from the configuration file's parent
directory.

Cyclopts provides the command-line interface and standard option parsing.
Hecate uses Python `tomllib` for lower-level policy loading and validation.
Python's `tomllib` reads TOML 1.0.0 and returns Python dictionaries, but does
not write TOML files.[^1]

## Minimal configuration

```toml
[tool.hecate]
root_packages = ["sample"]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["sample.domain"]
allowed = ["domain"]
```

## Full schema

```toml
[tool.hecate]
root_packages = ["beatcue"]
include_external_packages = true
default_rule_id = "HEC001"
unclassified_modules = "ignore"

[[tool.hecate.package]]
name = "beatcue"
root = "beatcue"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["beatcue.domain"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "application"
prefixes = ["beatcue.application"]
allowed = ["application", "domain"]
warn = ["legacy"]

[[tool.hecate.groups]]
name = "legacy"
prefixes = ["beatcue.legacy"]
allowed = ["legacy"]

[[tool.hecate.ignore_imports]]
importer = "beatcue.config"
imported = "beatcue.adapters.outbound"
reason = "Composition root wiring."
```

## Top-level keys

| Key                            | Type             | Required                                     | Description                                                                                                      |
| ------------------------------ | ---------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `root_packages`                | array of strings | Required unless `package` tables are present | Package names whose roots use the same relative path as the package name.                                        |
| `include_external_packages`    | boolean          | Optional                                     | Enables classification of external module prefixes such as `sqlalchemy` when matching groups declare them.       |
| `default_rule_id`              | string           | Optional                                     | Rule identifier used in diagnostics. Defaults to `HEC001`.                                                       |
| `strict`                       | boolean          | Optional                                     | Fails on unclassified and unresolved internal edges. Defaults to `false`.                                        |
| `unresolved_internal_severity` | string           | Optional                                     | Severity for unresolved internal edges under `strict`. One of `error`, `warning`, `exempt`. Defaults to `error`. |
| `unclassified_modules`         | string           | Optional                                     | How an internal module no group classifies is reported. One of `ignore`, `warn`, `error`. Defaults to `ignore`.  |
| `package`                      | array of tables  | Optional                                     | Explicit package name and root mappings.                                                                         |
| `groups`                       | array of tables  | Required                                     | Ordered architecture groups.                                                                                     |
| `ignore_imports`               | array of tables  | Optional                                     | Documented import edges to suppress.                                                                             |

_Table 1: Top-level `[tool.hecate]` keys._

Use `[[tool.hecate.package]]` when a package name does not match its source
directory:

```toml
[[tool.hecate.package]]
name = "public_name"
root = "src/internal_name"
```

## Group tables

Each `[[tool.hecate.groups]]` table has these keys:

| Key        | Type             | Required | Description                                         |
| ---------- | ---------------- | -------- | --------------------------------------------------- |
| `name`     | string           | Yes      | Unique group name.                                  |
| `prefixes` | array of strings | Yes      | Dotted module prefixes matched by this group.       |
| `allowed`  | array of strings | Yes      | Group names this group may import.                  |
| `warn`     | array of strings | No       | Group names this group may import at warning level. |

_Table 2: Architecture group keys._

Group matching is ordered. The first group whose prefix contains the module
wins. Prefix containment follows dotted module boundaries: `sample.api` matches
itself and descendants such as `sample.api.runtime`, but not lookalikes such as
`sample.apis`. Put specific prefixes before general prefixes.

Configuration is rejected when an earlier group's prefix is equal to or
contains a prefix in a later group. The later prefix cannot classify any
module, so a green check cannot rely on it. Prefixes in the same group may be
redundant; this check compares groups only. A narrow exception before a broad
prefix remains valid.

This order is rejected because `sample.api` wins before `sample.api.runtime`:

```toml
[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.api"]
allowed = ["inbound_adapter", "composition_root"]

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.api.runtime"]
allowed = ["composition_root", "inbound_adapter"]
```

Move the narrower group first to make the exception effective:

```toml
[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["sample.api.runtime"]
allowed = ["composition_root", "inbound_adapter"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["sample.api"]
allowed = ["inbound_adapter", "composition_root"]
```

A `warn` entry names a target the group may import, but whose edges Hecate
reports as warnings instead of passing them silently. Warning edges do not fail
the check unless the run asks them to; see
[warning-level directions](#warning-level-directions). If a target appears in
both `allowed` and `warn`, Hecate rejects the configuration rather than letting
the outcome depend on which check ran first.

## Ignore tables

Each `[[tool.hecate.ignore_imports]]` table has these keys:

| Key        | Type   | Required | Description                         |
| ---------- | ------ | -------- | ----------------------------------- |
| `importer` | string | Yes      | Importing module prefix.            |
| `imported` | string | Yes      | Imported module prefix.             |
| `reason`   | string | Yes      | Non-empty reason for the exception. |

_Table 3: Ignore keys._

Ignores match dotted descendants. An ignore for `sample.config` importing
`sample.adapters.outbound` also covers `sample.config.runtime` importing
`sample.adapters.outbound.db`.

## Strict mode

Strict mode closes the gap where an import edge matched no group and was
therefore never checked. Enable it globally:

```toml
[tool.hecate]
strict = true
```

Under strict mode:

- an unclassified internal edge fails the check;
- an unresolved internal edge fails, unless
  `unresolved_internal_severity` lowers it to a warning or `exempt`; and
- documented `ignore_imports` entries continue to exempt the edges they cover.

Strict mode applies to edges _within_ the scanned package roots. An external
import is in scope only when `include_external_packages` is enabled and a group
declares its prefix; an external prefix no group claims is skipped, so enabling
external classification never turns a third-party dependency into a failure by
itself. See [top-level keys](#top-level-keys).

Without strict mode these edges are still reported, but as warnings that do not
change the exit code. This lets an existing project adopt the policy without a
flag day, then tighten later.

## Policy coverage

Strict mode reports edges the policy could not classify. A module no group
claims is a related but separate gap: every import it makes or receives sits
outside group-based enforcement, so a package added without a matching prefix
can drift unchecked while every existing check still passes.

`unclassified_modules` closes that gap by reporting the module itself:

```toml
[tool.hecate]
unclassified_modules = "error"
```

The three modes are:

- `ignore` (default) — report nothing, preserving earlier behaviour.
- `warn` — report each unclassified module as a warning. The exit code does not
  change, matching the project's warning policy elsewhere.
- `error` — report each unclassified module as an error, failing the check with
  exit code 1.

Coverage of discovered modules is broader than coverage of scanned imports:

- Every `*.py` file beneath a configured package root is a discovered module,
  including `__init__.py` and files that import nothing. A new package is
  therefore visible on its first run, before it grows a single import.
- Classification uses the same ordered, first-match rule as edges. A dotted
  prefix matches at a boundary, so a group for `sample.domain` does not
  classify a lookalike `sample.domainx`.
- A package `__init__.py` is claimed when any configured prefix lies beneath
  it. An initializer imports and re-exports what its submodules bind, so a
  policy that governs `sample.domain` already governs the `sample.domain`
  package itself. Without this rule every conventional package would need a
  recursive group for its own root, and that group would then claim every
  future subpackage the module pass exists to find. The containment stops at
  the initializer: `sample.newthing` is a plain module and is still reported
  even when `sample` itself is an initializer some group covers.
- External imports are unaffected. They continue to follow
  `include_external_packages` and the external prefixes groups declare; a
  third-party dependency is not an unclassified internal module.
- Classified modules and their edges keep exactly their previous behaviour.
  Only modules matching no group are reported.
- Under `warn` and `error`, an import edge with an unclassified endpoint
  remains unchecked. The module-level finding exists to make that visible, not
  to change how such an edge is classified.

## Warning-level directions

A group may name targets it tolerates but wants to keep visible:

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

Here `sample.application` may import `sample.legacy`, and every such edge is
reported as a warning. The edge is classified, not exempted: it appears under
`warnings` in JSON output and as a `(warning):` line in text output, and it
does not fail the check by itself. Use this for a boundary a migration is
working towards, so the direction stays in CI output without blocking the
change that introduces it.

Hecate resolves an edge against the group's policy in this order:

1. an edge outside the scanned roots, or matching no group, is skipped or
   reported as coverage;
2. an `allowed` target passes silently;
3. a matching `ignore_imports` entry exempts the edge;
4. a `warn` target is reported as a warning; and
5. anything else is a violation.

`allowed` is checked before `ignore_imports`, so an ignore aimed at an edge the
policy already allows never matches. It stays visible as an unmatched ignore
rather than silently covering nothing.

## Validation rules

- Group names must be unique.
- Prefixes must be non-empty dotted strings.
- `allowed` and `warn` entries must refer to declared groups.
- A group may not list the same target in both `allowed` and `warn`.
- `warn` must be an array of non-blank strings when present.
- Ignores must include a non-empty reason.
- `unresolved_internal_severity` must be `error`, `warning`, or `exempt`.
- `unclassified_modules` must be `ignore`, `warn`, or `error`.
- `default_rule_id` must not be `HEC002`, which is reserved for
  unclassified-module diagnostics.
- Missing or non-directory package roots fail before scanning.
- Configuration errors include the TOML file path and the failing context.

## Command-line options

Supported options:

- `--config PATH`
- `--package NAME --root PATH`
- `--format text|json`
- `--include-external-packages`
- `--no-include-external-packages`
- `--strict`
- `--no-strict`
- `--show-ignored`
- `--show-coverage`
- `--fail-on-unmatched-ignore`
- `--fail-on-warnings`

`--package` and `--root` must be provided together. They override configured
package roots for ad hoc checks. `--strict` and `--no-strict` override the
configured `strict` value for a single run. `--fail-on-warnings` makes a run
that reported warning-level edges exit with code `1`; the diagnostics are
printed first, so the failing run still names the edges that caused it.

______________________________________________________________________

[^1]: Python documentation for
      [`tomllib`](https://docs.python.org/3/library/tomllib.html).
