# Architectural decision record (ADR) 002: four-tier Python commit-gate linting

## Status

Accepted. The Python commit gate combines format verification, Ruff,
PyPy-backed Pylint and Skylos dead-code detection.

## Date

2026-08-24.

## Context and problem statement

Hecate needs fast, broad lint feedback, a complementary static-analysis pass
and production dead-code detection. The latter must block commits and pull
requests without allowing test-only references to make production symbols look
live. It must also handle the project's supported Python syntax consistently.

## Decision outcome / proposed direction

Treat the complete Python commit gate as four ordered tiers:

1. `make check-fmt` verifies the Python formatting contract.
2. Ruff provides fast, broad Python lint rules through `make lint`.
3. PyPy-backed Pylint provides the established complementary analysis through
   `make lint`.
4. Skylos performs strict production dead-code detection through `make lint`.

Skylos scans `hecate`, excludes `tests`, enables strict gate mode and disables
uploads and provenance collection. It runs under Python 3.14 because Skylos
parses source using its own runtime AST; keeping that runtime current prevents
phantom dead-code findings from newer syntax.

Investigate every finding and remove genuine dead code. When a verified runtime
caller is not statically visible, record a precise typed entry point with its
fully qualified symbol, kind and caller-specific reason. Use the documented
allow list only when an entry-point rule cannot model the boundary. The
`skylos-allow` helper requires `SYMBOL` and `REASON` and dispatches the
`whitelist` subcommand before its arguments.

## Consequences

The local and continuous-integration lint gates share the same blocking Skylos
command. Makeutil parses the Makefile contract in the full test suite, so local
contributors and each coverage workflow install the pinned Makeutil revision
with its pinned nightly toolchain and Polonius flag. This adds a small
bootstrap requirement, but it makes command ordering, tool versions and CI
provisioning regressions observable before review.
