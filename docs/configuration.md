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

[[tool.hecate.ignore_imports]]
importer = "beatcue.config"
imported = "beatcue.adapters.outbound"
reason = "Composition root wiring."
```

## Top-level keys

| Key                         | Type             | Required                                     | Description                                                                                                |
| --------------------------- | ---------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `root_packages`             | array of strings | Required unless `package` tables are present | Package names whose roots use the same relative path as the package name.                                  |
| `include_external_packages` | boolean          | Optional                                     | Enables classification of external module prefixes such as `sqlalchemy` when matching groups declare them. |
| `default_rule_id`           | string           | Optional                                     | Rule identifier used in diagnostics. Defaults to `HEC001`.                                                 |
| `package`                   | array of tables  | Optional                                     | Explicit package name and root mappings.                                                                   |
| `groups`                    | array of tables  | Required                                     | Ordered architecture groups.                                                                               |
| `ignore_imports`            | array of tables  | Optional                                     | Documented import edges to suppress.                                                                       |

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

| Key        | Type             | Required | Description                                   |
| ---------- | ---------------- | -------- | --------------------------------------------- |
| `name`     | string           | Yes      | Unique group name.                            |
| `prefixes` | array of strings | Yes      | Dotted module prefixes matched by this group. |
| `allowed`  | array of strings | Yes      | Group names this group may import.            |

_Table 2: Architecture group keys._

Group matching is ordered. The first group whose prefix contains the module
wins. Put specific prefixes before general prefixes.

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

## Validation rules

- Group names must be unique.
- Prefixes must be non-empty dotted strings.
- `allowed` entries must refer to declared groups.
- Ignores must include a non-empty reason.
- Missing or non-directory package roots fail before scanning.
- Configuration errors include the TOML file path and the failing context.

## Command-line options

Supported options:

- `--config PATH`
- `--package NAME --root PATH`
- `--format text|json`
- `--include-external-packages`
- `--no-include-external-packages`
- `--show-ignored`
- `--fail-on-unmatched-ignore`

`--package` and `--root` must be provided together. They override configured
package roots for ad hoc checks.

______________________________________________________________________

[^1]: Python documentation for
      [`tomllib`](https://docs.python.org/3/library/tomllib.html).
