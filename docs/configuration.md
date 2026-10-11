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
wins. Put specific prefixes before general prefixes.

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
