# Architectural decision record (ADR) 001: stdlib `ast` import engine

## Status

Accepted. Hecate v1 uses the Python standard library `ast` module as its import
analysis engine.

## Date

2026-05-17.

## Context and problem statement

Hecate replaces bespoke architecture checkers from BeatCue and Episodic with a
reusable package. Both trials showed that Python parsing was not the hard reuse
problem. The hard parts were policy configuration, package-root handling,
package-barrel re-export semantics, deterministic diagnostics, documented
ignores, and reusable tests.

The checker must parse `import x` and `from x import y`, resolve relative
imports, expand statically visible `__init__.py` re-exports, and classify
imports against TOML policy. It does not execute imports or perform semantic
inference.

## Decision drivers

- Keep v1 small enough to audit and maintain internally.
- Avoid runtime import loading and dynamic execution.
- Keep policy semantics independent of the parsing engine.
- Support deterministic diagnostics suitable for CI snapshots.
- Leave room for Astroid or another engine behind an interface later.

## Options considered

| Option        | Strengths                                                                                   | Weaknesses                                                                           | Outcome                             |
| ------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ----------------------------------- |
| stdlib `ast`  | No parser dependency; stable syntax tree for import statements; enough for v1 requirements. | No semantic inference; cannot resolve dynamic imports.                               | Accepted for v1.                    |
| Astroid       | Offers inference and richer Python object modelling.                                        | Adds dependency and false-confidence risk before projects prove inference is needed. | Deferred.                           |
| Semgrep       | Strong local syntax-rule engine and useful for non-graph checks.                            | Not the core import graph engine; policy and re-export handling remain custom work.  | Out of scope for v1 graph checking. |
| Import Linter | Mature architecture-linting concepts such as forbidden and layered contracts.               | Hecate needs df12-specific TOML shape, re-export semantics, and migration path.      | Borrow concepts, not dependency.    |

_Table 1: Import analysis options considered for Hecate v1._

## Decision outcome / proposed direction

Use stdlib `ast` for Hecate v1. Keep parsing in `hecate/imports.py`, re-export
expansion in `hecate/reexports.py`, policy in `hecate/policy.py`, and rendering
in `hecate/output.py`. This keeps parser, policy, and output layers separate
enough for another engine to be introduced later without changing the TOML
policy schema.

## Goals and non-goals

- Goals:
  - Parse direct and `from` imports using stdlib `ast`.
  - Resolve relative imports against the importing module.
  - Expand explicit and statically resolvable star re-exports.
  - Emit stable text and JSON diagnostics.
  - Keep project policy in TOML rather than Python code.
- Non-goals:
  - Execute imports through `importlib`.
  - Infer dynamic imports or runtime aliasing.
  - Add Semgrep or Astroid as v1 dependencies.
  - Rewrite imports automatically.
  - Support non-Python languages.

## Known risks and limitations

- Dynamic imports are invisible to v1.
- Non-literal `__all__` falls back to public symbols instead of evaluating code.
- Star exports are expanded only when the exporting module can be resolved
  statically from source.
- External packages are classified by configured prefixes, not by installed
  distribution metadata.
- CrossHair validation is limited to bounded pure helpers and deliberately
  excludes filesystem, `ast.parse`, TOML parsing, and CLI code.

## Architectural rationale

Hexagonal architecture enforcement is a policy problem over import edges. The
stdlib parser provides those edges with low operational cost. Keeping the graph
engine simple makes the policy surface, diagnostics, ignores, and migration
fixtures the centre of the design, which matches the lessons from BeatCue and
Episodic.

The design borrows concepts from Import Linter forbidden contracts, layered
contracts, external-package handling, and ignore entries[^1], while keeping
Hecate's configuration focused on ordered groups and allowed dependencies.[^2]

______________________________________________________________________

[^1]: Import Linter forbidden contracts:
    <https://import-linter.readthedocs.io/en/stable/contract_types/forbidden/>.
[^2]: Import Linter layers contracts:
    <https://import-linter.readthedocs.io/en/stable/contract_types/layers/>.
