# Hecate roadmap

## Status and scope

Proposed, 2026-09-16. This roadmap covers P1 through P3 of the Hecate/Mille
comparison follow-up. It describes future work, not shipped commands. No task
below is complete merely because this documentation merges.

[P0 issue #104](https://github.com/leynos/hecate/issues/104) owns
explicit-import versus `__all__` semantics, consumer wildcards, and visible
unclassified or unresolved coverage. P1 can develop fixtures alongside that
work. P1 sign-off and authoritative P2/P3 rollout require its acceptance
criteria to pass. Do not close #104 from a documentation-only pull request (PR).

The accepted [ADR 001](adr-001-stdlib-ast-import-engine.md) remains binding:
standard-library abstract syntax tree (AST) parsing, no execution of analysed
projects, Python-only scope, and a small auditable implementation. Its current
non-literal `__all__` fallback must be reconciled with #104 before claiming
strict coverage. These requests for comments (RFCs) propose extensions, not
silent amendments to that architectural decision record (ADR).

## Goals, ideas, steps, and tasks

The Goals, Ideas, Steps, and Tasks (GIST) framework distinguishes desired
outcomes from hypotheses and the experiments that test them.[^1] Here, phases
organize outcomes, numbered steps test ideas, and checkbox tasks identify
bounded delivery units. Dates are not delivery commitments.

| Goal | Outcome and evidence required |
| --- | --- |
| G1: Trustworthy checks | Every required corpus case passes its independent expectation; no unexpected green result hides an unclassified or unresolved in-scope import. Publish limitations separately. |
| G2: Explainable decisions | Every diagnostic in the acceptance corpus identifies its source, resolution evidence, rule, and any exception; graph and command views agree. |
| G3: Safe adoption | Both migration-derived fixtures support discover, review, enforce, and rollback without automatically permitting observed violations or losing exception reasons. |

_Table 1: Goals and measurable completion evidence._

Ideas remain hypotheses until the linked step produces evidence. A rejected idea
retains its identifier and decision record; it does not become a new mandatory
feature under another name.

| Idea | Hypothesis and validation | Goals | Phase / steps | Task mapping | Design |
| --- | --- | --- | --- | --- | --- |
| I1: Independent conformance | Semantic fixtures and an independent oracle expose regressions that implementation-shaped tests miss. | G1 | P1 / 1.1, 1.2 | 1.1.1–1.1.3; 1.2.1–1.2.2 | [RFC 001 §3–5](rfc-001-conformance-corpus.md#3-corpus-contract) |
| I2: Evidence-led differentiation | Equivalent-policy comparisons and migration fixtures establish whether an independent checker remains worthwhile. | G1, G3 | P1 / 1.2, 1.3 | 1.2.3; 1.3.1–1.3.2 | [RFC 001 §6–7](rfc-001-conformance-corpus.md#6-comparison-and-cost-controls) |
| I3: Shared analysis records | One provenance-preserving result prevents reporting and enforcement from disagreeing. | G1, G2 | P2 / 2.1 | 2.1.1–2.1.3 | [RFC 002 §3–4](rfc-002-explainable-analysis.md#3-analysis-contract) |
| I4: Actionable views | Explanations, graphs, and annotations provide enough evidence to repair rather than suppress violations. | G2 | P2 / 2.2, 2.3 | 2.2.1–2.2.3; 2.3.1–2.3.2 | [RFC 002 §5–7](rfc-002-explainable-analysis.md#5-command-and-output-contracts) |
| I5: Explicit external policy | Separate external defaults prevent new dependencies from disappearing between group definitions. | G1, G3 | P3 / 3.1 | 3.1.1–3.1.3 | [RFC 003 §3](rfc-003-safe-policy-adoption.md#3-external-dependency-policy) |
| I6: Reviewed bootstrapping | Discovery and a non-destructive candidate file reduce configuration work without approving existing architecture. | G3 | P3 / 3.2 | 3.2.1–3.2.3 | [RFC 003 §4](rfc-003-safe-policy-adoption.md#4-discovery-and-candidate-generation) |
| I7: Controlled adoption | Severity and failure thresholds support incremental enforcement without disguising exemptions or uncertainty. | G2, G3 | P3 / 3.3 | 3.3.1–3.3.3 | [RFC 003 §5–6](rfc-003-safe-policy-adoption.md#5-severity-exceptions-and-exit-status) |

_Table 2: GIST traceability from ideas to roadmap execution units._

## Dependency and design conventions

Every task records `Requires`, `Evidence`, and a design signpost. Requirements
are conjunctive. `None` means work may start immediately; `P0` means verified
completion of #104, not merely closing the issue. Task identifiers remain stable
when sequencing changes. Check a task only after linking its delivery PR and
validation evidence beside the checkbox.

RFCs define architecture; an accepted ADR records changes to binding invariants;
a milestone execution plan describes implementation tactics. Design signposts
name current seams, not instructions to build a general plugin framework. Where
P0 changes a seam, adapt to its accepted model rather than adding a parallel
representation.

The main dependency spine is:

```plaintext
P0 + 1.1 + 1.2 + 1.3 -> P1 evidence gate
P1 evidence gate -> 2.1 shared result -> 2.2 views -> 2.3 P2 gate
P2 gate -> 3.1 external policy -> 3.2 reviewed init -> 3.3 P3 gate
```

_Figure 1: Release dependency spine; individual task requirements below are more
precise and allow preparatory work in parallel._

## 1. P1: Establish conformance and differentiation

Outcome: a reproducible correctness argument and an explicit continue,
integrate, or retire decision. Design: [RFC 001](rfc-001-conformance-corpus.md).

### 1.1. Specify independent expectations

- [ ] 1.1.1. Define a versioned fixture manifest and outcome vocabulary.
  Requires: None. Evidence: schema rejects missing expectations, duplicate case
  IDs, and unsupported versions. Design: [RFC 001
  §3](rfc-001-conformance-corpus.md#3-corpus-contract).
- [ ] 1.1.2. Add the core import and P0 regression catalogue. Requires: 1.1.1.
  Evidence: every required family in §4 has positive and negative cases; known
  failures link #104 rather than changing the oracle. Design: [RFC 001
  §4](rfc-001-conformance-corpus.md#4-fixture-catalogue).
- [ ] 1.1.3. Add ambiguity, layout, and metamorphic cases. Requires: 1.1.2.
  Evidence: aliases, relocation, and enumeration order preserve expected
  meaning; unsupported dynamic cases report limitations explicitly. Design: [RFC
  001 §4](rfc-001-conformance-corpus.md#4-fixture-catalogue).

### 1.2. Exercise independent and comparative runners

- [ ] 1.2.1. Implement the controlled Python semantic oracle. Requires: 1.1.2.
  Evidence: fixture-owned execution agrees with hand-reviewed namespace
  expectations and cannot select an arbitrary repository to import. Design: [RFC
  001 §5](rfc-001-conformance-corpus.md#5-runners-and-trust-boundary).
- [ ] 1.2.2. Add Hecate's corpus adapter and offline regression gate. Requires:
  1.1.3, 1.2.1, P0. Evidence: all required cases pass with no expected-failure
  exemptions; existing tests still run independently. Design: [RFC 001
  §5](rfc-001-conformance-corpus.md#5-runners-and-trust-boundary).
- [ ] 1.2.3. Add an opt-in, version-pinned Mille comparison adapter. Requires:
  1.1.1, 1.2.1. Evidence: equivalent-policy cases compare normalized results;
  unsupported cases, crashes, and timeouts cannot count as passes. Design: [RFC
  001 §6](rfc-001-conformance-corpus.md#6-comparison-and-cost-controls).

### 1.3. Validate repository value and decide

- [ ] 1.3.1. Encode reviewed BeatCue- and Episodic-derived acceptance fixtures.
  Requires: 1.2.2. Evidence: both include roots, barrel imports, allowed and
  forbidden edges, documented exceptions, and unmatched-exception checks;
  fixture provenance and permitted redistribution are recorded. Design: [RFC 001
  §7](rfc-001-conformance-corpus.md#7-evidence-and-continuation-gate).
- [ ] 1.3.2. Publish the P1 evidence report and continuation decision. Requires:
  1.2.2, 1.2.3, 1.3.1. Evidence: pinned inputs, complete case outcomes,
  false-positive/negative counts, limitations, reproducibility instructions, and
  bounded runtime/memory measurements support an explicit decision. Design: [RFC
  001 §6–7](rfc-001-conformance-corpus.md#6-comparison-and-cost-controls).

P1 exit gate: all required Hecate cases pass; #104's regressions remain in the
corpus; the decision in 1.3.2 authorizes continuation. An unavailable peer run
is reported as missing evidence and requires an explicit decision exception, not
an invented comparative result.

## 2. P2: Expose explainable analysis

Outcome: one evidence model supports checking, discovery, and explanations.
Design: [RFC 002](rfc-002-explainable-analysis.md). Start with one vertical
slice, not a whole-engine rewrite.

### 2.1. Introduce the shared result incrementally

- [ ] 2.1.1. Implement a direct-import slice of the analysis contract. Requires:
  1.3.2, P0. Evidence: one fixture flows from source occurrence to resolution,
  policy assessment, and existing check output unchanged in shape. Design: [RFC
  002 §3–4](rfc-002-explainable-analysis.md#3-analysis-contract).
- [ ] 2.1.2. Preserve provenance and coverage for the complete supported corpus.
  Requires: 2.1.1. Evidence: all occurrences reconcile with coverage buckets;
  cycles terminate; unresolved and unclassified records remain inspectable.
  Design: [RFC 002 §3–4](rfc-002-explainable-analysis.md#3-analysis-contract).
- [ ] 2.1.3. Publish a versioned report serializer and compatibility fixtures.
  Requires: 2.1.2. Evidence: schema validation and normalized golden files
  agree; legacy JSON and documented exception behaviour retain their contract.
  Design: [RFC 002
  §5](rfc-002-explainable-analysis.md#5-command-and-output-contracts).

### 2.2. Deliver discovery and explanation views

- [ ] 2.2.1. Add policy-optional analysis and JSON/DOT graph views. Requires:
  2.1.3. Evidence: root-only analysis does not fabricate an allow-all policy;
  direct and origin-derived edges remain distinguishable in both views. Design:
  [RFC 002 §5](rfc-002-explainable-analysis.md#5-command-and-output-contracts).
- [ ] 2.2.2. Add source- and edge-addressable explanations. Requires: 2.1.3.
  Evidence: every acceptance diagnostic explains its import, origin chain or
  uncertainty, matched rule, and exception without guessing a fix. Design: [RFC
  002 §5](rfc-002-explainable-analysis.md#5-command-and-output-contracts).
- [ ] 2.2.3. Add the external-import inventory view. Requires: 2.2.1. Evidence:
  module prefixes, importing groups, source sites, counts, and excluded/unknown
  categories agree with the shared report; no installed-distribution lookup is
  necessary. Design: [RFC 002
  §5](rfc-002-explainable-analysis.md#5-command-and-output-contracts).

### 2.3. Validate CI and consumer compatibility

- [ ] 2.3.1. Add escaped GitHub Actions annotations. Requires: 2.2.2. Evidence:
  source locations and rule identifiers survive rendering; hostile
  paths/messages cannot inject workflow commands; checks retain their
  exit-status semantics independently of annotation output. Design: [RFC 002
  §6](rfc-002-explainable-analysis.md#6-ci-safety-and-resource-bounds).
- [ ] 2.3.2. Run the P2 acceptance and compatibility gate. Requires: 2.2.1,
  2.2.2, 2.2.3, 2.3.1. Evidence: corpus and migration fixtures agree across
  views; help, users' guide, schemas, and ADR changes describe only implemented
  behaviour; compare runtime/memory against P1 measurements. Design: [RFC 002
  §7](rfc-002-explainable-analysis.md#7-rollout-alternatives-and-acceptance).

P2 exit gate: 2.3.2 passes without losing P1 coverage or weakening P0 semantics.
A report states its static scope; it never claims that arbitrary dynamic Python
behaviour has been proven safe.

## 3. P3: Make adoption explicit and reversible

Outcome: discover, review, and enforce policy without converting observations
into permission. Design: [RFC 003](rfc-003-safe-policy-adoption.md).

### 3.1. Add explicit external-dependency policy

- [ ] 3.1.1. Specify and validate external modes and compatibility translation.
  Requires: 2.3.2. Evidence: a decision table covers allowlist, denylist,
  observation, standard-library handling, ambiguous ownership, and conflicting
  legacy/new settings. Design: [RFC 003
  §3](rfc-003-safe-policy-adoption.md#3-external-dependency-policy).
- [ ] 3.1.2. Evaluate external rules with source-level explanations. Requires:
  3.1.1, 2.2.3. Evidence: a previously unseen external prefix follows the
  declared default; legacy-only fixtures retain their documented policy. Design:
  [RFC 003 §3](rfc-003-safe-policy-adoption.md#3-external-dependency-policy).
- [ ] 3.1.3. Document migration and extend external conformance coverage.
  Requires: 3.1.2. Evidence: tests cover dotted-prefix boundaries, internal
  shadowing, standard-library names, missing targets, and CLI precedence;
  reviewed examples demonstrate restrictive and observational configurations.
  Design: [RFC 003
  §3](rfc-003-safe-policy-adoption.md#3-external-dependency-policy).

### 3.2. Bootstrap candidate configuration safely

- [ ] 3.2.1. Discover candidate roots and groups without writing policy.
  Requires: 2.2.1, 2.2.3. Evidence: flat, source-directory, and multi-root cases
  produce deterministic suggestions; ambiguous roots require explicit input.
  Design: [RFC 003
  §4](rfc-003-safe-policy-adoption.md#4-discovery-and-candidate-generation).
- [ ] 3.2.2. Generate a reviewable candidate file without overwriting input.
  Requires: 3.2.1, 3.1.3. Evidence: generated TOML round-trips; repeated runs
  are deterministic; existing policy and exceptions remain byte-for-byte intact;
  observation never synthesizes permission or an exemption. Design: [RFC 003
  §4](rfc-003-safe-policy-adoption.md#4-discovery-and-candidate-generation).
- [ ] 3.2.3. Exercise candidate review against both migration fixtures.
  Requires: 3.2.2, 1.3.1. Evidence: a forbidden existing edge remains visible
  before approval; explicit configuration selection and rollback work without
  editing the original file. Design: [RFC 003
  §6](rfc-003-safe-policy-adoption.md#6-migration-and-acceptance).

### 3.3. Support controlled enforcement and re-evaluate value

- [ ] 3.3.1. Separate diagnostic severity from policy truth and exceptions.
  Requires: 3.1.3, 2.1.3. Evidence: changing severity does not erase a forbidden
  edge or its reason; invalid configuration and strict coverage failures cannot
  silently become passing warnings. Design: [RFC 003
  §5](rfc-003-safe-policy-adoption.md#5-severity-exceptions-and-exit-status).
- [ ] 3.3.2. Add explicit failure thresholds and adoption documentation.
  Requires: 3.3.1, 3.2.3. Evidence: exit-status matrices cover strict and
  observational runs, stale exceptions, and legacy defaults; reports distinguish
  policy compliance from whether a configured gate passes. Design: [RFC 003
  §5–6](rfc-003-safe-policy-adoption.md#5-severity-exceptions-and-exit-status).
- [ ] 3.3.3. Publish the P3 acceptance and continuation review. Requires: 3.3.2,
  2.3.2. Evidence: both adoption journeys pass, all required corpus cases remain
  green, backward compatibility is documented, and updated comparison evidence
  supports keeping, integrating, or retiring Hecate. Design: [RFC 003
  §6–7](rfc-003-safe-policy-adoption.md#6-migration-and-acceptance).

P3 exit gate: 3.3.3 records the adoption evidence and decision. No automatic
baseline, source rewrite, new language front end, method-call inference,
keyword-ban engine, hosted service, or custom SVG renderer enters this scope.

## Delivery and validation discipline

Each implementation PR names its GIST idea, roadmap task, dependencies, design
section, and tests. New behaviour needs unit and behavioural tests before
implementation; refactors retain existing behaviour tests. Follow
[AGENTS.md](../AGENTS.md) and the [documentation style
guide](documentation-style-guide.md). Record unavailable checks explicitly
rather than treating them as passes.

Use small offline fixtures in ordinary continuous integration (CI). Comparative
runs remain opt-in and pinned, with trusted binaries and cached dependencies. Do
not introduce source builds or recurring heavyweight workflows for the
comparison. Task 1.3.2 establishes measured resource baselines, not invented
speed targets. RFC 001 defines the bounded runner policy.

The roadmap is the execution index; GitHub issues and PRs supply delivery
evidence. Maintain task status here without automatically creating a second
programme-tracking system or an issue for every checkbox.

[^1]: Itamar Gilad, [The GIST Board and Other GIST
    Tools](https://itamargilad.com/the-gist-board-and-other-gist-tools/).
