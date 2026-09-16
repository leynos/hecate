# RFC 001: Independent import conformance and comparison

## Status and scope

Proposed, 2026-09-16. Implements the design for [roadmap phase
1](roadmap.md#1-p1-establish-conformance-and-differentiation), ideas I1 and I2.
P0 correctness implementation remains in [issue
#104](https://github.com/leynos/hecate/issues/104). This document does not
assert new benchmark results or treat a peer checker as the oracle.

## 1. Context and design signposts

[ADR 001](adr-001-stdlib-ast-import-engine.md) identifies package roots,
re-exports, deterministic diagnostics, and documented exceptions as Hecate's
reuse problems. The current seams are [imports](../hecate/imports.py),
[re-exports](../hecate/reexports.py), [checking](../hecate/checker.py), and
[policy](../hecate/policy.py). Extend [tests](../tests/) rather than replacing
existing unit coverage with CLI snapshots.

A semantic model can be wrong even when its own tests pass. For example,
Python's explicit imports consult module attributes; `__all__` selects wildcard
exports and does not hide an existing explicitly requested attribute.[^1] The
corpus must distinguish those language facts from architectural policy.

## 2. Goals and non-goals

The goal is independently specified, reproducible evidence for supported static
analysis and explicit limits for unsupported cases. Comparable peer results
inform maintenance decisions. They do not define Python semantics.

Non-goals include proving arbitrary Python execution safe, importing production
projects, a general benchmark service, a multi-language fixture language,
rewriting the parser, or making every peer support Hecate-specific policy.

## 3. Corpus contract

Use repository-owned directories under a proposed `tests/conformance/` root,
with source files, a versioned JSON manifest, and separate expected results.
Reuse the existing test framework and standard-library JSON parsing. Add no
runtime dependency to Hecate for comparative testing.

Each manifest records a stable case ID, rationale, Python-version constraints,
package-root mappings, policy input, and expected source occurrences, resolved
names/origins, uncertainty, policy outcomes, and exception reasons. Include
whether runtime-oracle execution is permitted for that fixture. The manifest
must identify which assertion depends on language semantics and which depends on
the configured architectural rule.

Required outcomes distinguish resolved from unresolved analysis and permitted,
forbidden, exempted, unclassified, or unevaluated policy. A runner also records
unsupported, skipped, timeout, and crash states. Those runner states never
normalize to a successful policy check. An unsupported required Hecate case
fails the phase gate; a documented dynamic limitation occupies a separate
non-required category and remains visible in reports.

Record expected semantics manually with reviewer rationale. Do not generate
expectations from Hecate, from Mille, or from a majority vote between tools.
Malformed manifests fail collection, including duplicate IDs and unknown schema
versions. Raw tool output remains available alongside normalization.

## 4. Fixture catalogue

| Family | Required distinctions |
| --- | --- |
| Direct and relative imports | Absolute imports, aliases, multiline imports, one and multiple leading dots, `from . import child`, package initializers, and ascent beyond the package root. |
| Explicit bindings and exports | Explicit names omitted from `__all__`, empty/later literal assignments, default public names, underscore names, and module-versus-attribute ambiguity. |
| Barrel provenance | Named chains, wildcard producers, wildcard consumers, cycles, repeated routes, name shadowing, and rebinding. |
| Policy and coverage | Allowed/forbidden pairs, first-match group order, dotted-prefix boundaries, unclassified importer/target, unresolved target, and disabled external checking. |
| Exceptions | Non-empty reasons, descendant matching, overlapping entries, unmatched exceptions, and stable reporting. |
| Source layout | Flat roots, `src` roots, explicit name/path mappings, multiple roots, and ambiguous or namespace layouts with explicit support status. |
| Bounded limitations | Non-literal exports, conditional bindings, dynamic imports, and module `__getattr__`; require honest uncertainty where static support does not exist. |

_Table 1: Conformance families and their independent assertions._

Every supported semantic family needs positive and negative policy examples.
Unknown behaviour must not acquire a guessed resolved origin to satisfy a test.
Conditional and type-checking-only imports need a documented static policy;
runtime execution of one branch cannot establish all possible dependencies.

Metamorphic checks vary import aliases, supported equivalent absolute/relative
forms, file enumeration, checkout locations, and irrelevant source content.
Compare semantic identities separately from source-line changes. A test that
changes package layout must preserve its explicit root mapping before claiming
equivalence.

## 5. Runners and trust boundary

Build a small runner per checker rather than a production plugin architecture.
The Hecate runner first exercises public checking behaviour; P2 later adds
assertions over the richer analysis result without changing the expected facts.

A separate Python oracle may execute only reviewed, fixture-owned programs in
fresh temporary directories and isolated subprocesses. Pin the interpreter,
control import paths, bound time/output, and avoid third-party dependencies or
network access. Give fixtures explicit origin sentinels where useful; do not
assume `__module__` reveals the origin of arbitrary values. Validate namespace
availability and origin bindings independently of policy decisions.

An isolated subprocess is not a security sandbox. Never run the oracle against
user-supplied roots, arbitrary repository contents, or downloaded peer fixtures.
The production checker continues to parse without executing imports. This
boundary must have a test that rejects non-corpus input.

During P0 development, a narrowly named expected failure may identify #104. At
P1 sign-off, all required cases must pass without expected-failure markers.
Existing tests remain separate, including bounded pure-helper verification;
those checks are not an import-pipeline proof.

## 6. Comparison and cost controls

Pin the Mille package version or release commit, artifact checksum, platform,
Python version, Hecate commit, corpus revision, command lines, and translated
configuration in each comparison report. Verify the selected release when the
run occurs; do not bake an unverified claim about the latest version into CI.

Compare only equivalent policy expressiveness and source scope. Where a peer
cannot express provenance rules or reason-bearing exceptions, label the case
non-comparable and explain why. Report false positives and false negatives only
for cases with defined expectations; show denominators and unsupported counts
separately. Preserve a green peer result that misses a required forbidden edge
as a false negative, not an unsupported pass.

The default CI path uses offline Hecate fixtures. Peer execution is an explicit
local or manually triggered job, not a new schedule. Prefer a verified binary or
compatible wheel; never silently fall back to a source build. Missing artifacts
fail setup or produce an explicit unavailable comparison. Cache any installed
tools and dependencies with version/platform-aware keys.

Use at most 4 virtual CPUs and 8 GiB for build jobs, and 1 virtual CPU and 2 GiB
for non-build comparison/report jobs. Start fixture subprocess limits at 10
seconds and 1 MiB captured output per case, with a 10-minute suite limit;
changes require recorded measurements. Resource exhaustion is an explicit runner
outcome. Report repeated cold/warm runtime and peak memory with hardware and
cache conditions, not performance inferred from implementation language.

## 7. Evidence and continuation gate

Derive compact, redistributable acceptance fixtures from the documented
[BeatCue](migration-beatcue.md) and [Episodic](migration-episodic.md)
migrations. Record provenance and review permission before copying production
examples; use synthetic equivalents when copying is inappropriate. Live
repository runs are optional corroboration and must pin commits and redact
sensitive outputs.

The P1 report contains per-case results, normalization limitations, config
translations, resource observations, install failures, and reproduction steps.
It explicitly evaluates these alternatives:

- Continue Hecate when required semantics and exception evidence justify the
  incremental maintenance cost.
- Contribute upstream or build a thin integration when another checker can
  preserve the required contracts with less maintenance.
- Retire the independent checker when an alternative meets the accepted corpus
  and adoption needs; a bespoke TOML shape alone is not sufficient
  justification.

The maintainer records the decision and evidence, not a weighted score invented
in advance. An unavailable comparison needs a documented exception and cannot
support a superiority claim. Keep genuine upstream defects separate from
longer-term product differentiation.

## 8. Acceptance and rollout

Tasks 1.1.1–1.1.3 establish fixtures; 1.2.1–1.2.3 add independent and
comparative runners; 1.3.1–1.3.2 establish repository evidence and the
continuation gate. The [roadmap](roadmap.md) owns dependency and completion
state.

Before acceptance, reviewers approve the manifest version, required-versus-
limitation catalogue, oracle boundary, and normalization rules. Run malformed
manifest tests, required Hecate cases, controlled oracle tests, and
deterministic report tests. Record any new semantic limitation in the ADR and
users' guide. No compiler, hosted service, or periodic workflow is necessary for
this phase.

[^1]: Python language reference, [the import
    statement](https://docs.python.org/3/reference/simple_stmts.html#the-import-statement).
