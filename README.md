# hecate

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](
https://deepwiki.com/leynos/hecate)

`hecate` is a standalone Python architecture checker for df12 internal projects
that use hexagonal architecture. It scans Python package roots with the
standard library `ast` module, classifies imports into configured groups,
expands package-barrel re-exports, and reports deterministic diagnostics for
Continuous Integration (CI).

## Quick start

Install the package into the project environment, then add a `[tool.hecate]`
section to `pyproject.toml`:

```toml
[tool.hecate]
root_packages = ["beatcue"]
include_external_packages = true
default_rule_id = "HEC001"

[[tool.hecate.groups]]
name = "domain"
prefixes = ["beatcue.domain"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "application"
prefixes = ["beatcue.application"]
allowed = ["application", "domain"]
```

Run the checker from the repository root:

```bash
hecate check
python -m hecate check
```

Use an explicit TOML file when the policy is not in `pyproject.toml`:

```bash
hecate check --config architecture.toml
```

Emit machine-readable diagnostics for CI integrations:

```bash
hecate check --format json
```

## Exit codes

- `0`: no architecture violations were found.
- `1`: architecture violations were found.
- `2`: command-line input, configuration, or package-root validation failed.

## Core concepts

Hecate models policy as ordered architecture groups. The first matching group
wins, so specific prefixes such as `beatcue.adapters.outbound` should appear
before broader prefixes such as `beatcue.adapters`.

Each group declares the groups it may import. This supports common hexagonal
architecture shapes:

- domain modules may import only domain modules;
- application modules may import application and domain modules;
- inbound adapters may invoke application services and, where explicitly
  configured, composition roots;
- outbound adapters may implement application or domain ports and use
  infrastructure packages;
- composition roots may wire the system together through explicit exceptions.

Hecate expands `__init__.py` re-exports, including statically resolvable star
exports. A forbidden adapter import remains visible even when it is hidden
behind a package barrel.

## Validation

The local validation gates are:

```bash
make check-fmt
make lint
make typecheck
make test
make crosshair
```

`make crosshair` runs bounded assert-based contracts over pure helper logic in
`hecate/policy.py` and `hecate/diagnostics.py`. It intentionally avoids
filesystem, `ast.parse`, TOML parsing, and CLI code.

## Documentation

- [Configuration schema](docs/configuration.md)
- [Users' guide](docs/users-guide.md)
- [BeatCue migration notes](docs/migration-beatcue.md)
- [Episodic migration notes](docs/migration-episodic.md)
- [ADR 001: use stdlib `ast` for v1 import analysis](docs/adr-001-stdlib-ast-import-engine.md)
- [ADR 002: four-tier Python commit-gate linting and Skylos contracts](docs/adr-002-four-tier-python-linting.md)
