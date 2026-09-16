# RFC 003: Explicit external policy and safe adoption

## Status and scope

Proposed, 2026-09-16. Implements the design for [roadmap phase
3](roadmap.md#3-p3-make-adoption-explicit-and-reversible), ideas I5, I6, and I7.
Requires P2's versioned analysis report and preserves [P0 issue
#104](https://github.com/leynos/hecate/issues/104) coverage guarantees. All new
configuration and command surfaces remain proposals until implemented.

## 1. Context and design signposts

The current [configuration](configuration.md) uses ordered groups,
`include_external_packages`, explicit package roots, and reason-bearing
`ignore_imports`. [Configuration loading](../hecate/config.py),
[policy](../hecate/policy.py), [checking](../hecate/checker.py), and [CLI
handling](../hecate/cli.py) are the relevant seams.

Discovery describes existing imports; it does not establish that those imports
are architecturally acceptable. External defaults, generated candidates, and
severity controls must preserve that distinction. Use [RFC
002](rfc-002-explainable-analysis.md)'s shared report instead of rescanning
files independently in configuration generation or reporting.

## 2. Goals and exclusions

Support explicit external-dependency defaults, useful candidate configuration,
and staged enforcement with reversible changes. Preserve first-match internal
group selection, dotted-prefix boundaries, documented exceptions, and stale-
exception detection.

Exclude automatic source changes, automatic grandfathering of violations,
blanket file exclusions as a migration strategy, package installation to resolve
imports, distribution-name inference, arbitrary method-call restrictions, and
multi-language expansion.

## 3. External-dependency policy

Introduce a separately validated external-policy section. The implementation
must document its exact TOML keys and CLI precedence before exposing it; the
semantic contract below is the acceptance criterion, not an undocumented
configuration example.

| Mode | Matching prefix | Previously unseen external prefix |
| --- | --- | --- |
| Allowlist | Permit only explicitly listed dotted prefixes in the importing group's external rule. | Forbidden. |
| Denylist | Forbid explicitly listed dotted prefixes; permit other known external prefixes. | Permitted by an explicit default, recorded in the explanation. |
| Observe | Inventory the dependency with no permission assertion. | Not evaluated, visible in coverage and adoption reports. |

_Table 1: Proposed external policy modes and explicit defaults._

Provide a global default and an optional per-importer-group replacement rule.
Choose the importer using the existing first-match group policy; a group
override replaces rather than implicitly unions with the global rule. Reject
multiple rules for the same scope and allow/deny fields incompatible with the
selected mode. An unclassified importer remains unclassified, not a wildcard
scope.

Match module prefixes on dotted boundaries, so `sql` does not match
`sqlalchemy`. Separate standard-library treatment from third-party defaults with
explicit allow, deny, or observe behaviour. Use the declared analysis
interpreter's standard-library name catalogue, report that version/platform, and
check configured internal ownership first to handle shadowing. Analysing a
different interpreter target requires a supplied catalogue or an explicit
unsupported result; do not silently use the host's view.

An internal-looking but missing target remains unresolved internal, not a new
external package. Ambiguous namespace ownership stays unknown. Do not execute
imports, inspect installed packages to guess ownership, or equate Python import
prefixes with package-distribution names.

Legacy-only configuration retains its documented external inclusion and group
semantics. When the new section is present, it becomes the sole external-policy
authority. Reject simultaneous legacy external toggles or conflicting external
group prefixes rather than choosing silently. Migration tooling must identify
and explain those conflicts. Existing CLI precedence remains unchanged for
legacy configurations; new options need equivalent validation and documented
precedence, not hidden overrides.

Keep external inclusion/observation separate from internal strict coverage.
External observation cannot authorize dropping an unresolved internal edge.
Reason-bearing import-edge exceptions remain available only as explicit,
reported exceptions to evaluated rules.

## 4. Discovery and candidate generation

Proposed `hecate init` discovers candidate roots/groups and emits a candidate
configuration plus an evidence report. Root discovery can use explicit mappings,
packaging metadata, and filesystem layout. Support reviewed flat, `src`, and
multi-root cases; when heuristics disagree, show alternatives and require an
explicit root mapping rather than selecting the broadest scan.

The first implementation writes a standalone file selected with existing
`--config`, not an in-place `pyproject.toml` editor. Default to a preview; an
explicit output path permits creation only when the destination does not exist.
Refuse to overwrite files, follow output symlinks, or mutate the input policy.
Use atomic exclusive publication or equivalent no-clobber handling so a race
cannot replace an existing file. Preserve original policy bytes and comments by
not editing that file at all.

Emit observed dependencies in an adjacent report, not as generated `allowed`
entries. Candidates contain root/group suggestions and the minimum valid
restrictive policy chosen explicitly for review. Do not add even self-group
permissions unless the user has approved the relevant template. External policy
defaults must be selected or remain visibly observational; observation is not a
production compliance claim. Never manufacture exception reasons.

A candidate may parse successfully and still fail architecture checks. That is
expected: syntax validity and policy approval are different gates. Round-trip
generated TOML through the real loader and make repeated generation from the
same inputs deterministic. Since the standard library reader does not write
TOML, choose a small deterministic serializer for the constrained candidate
schema or justify a narrowly scoped writer dependency in an ADR. Do not build a
general TOML rewriting engine for this milestone.

On an existing project, discovery reads and reports the current policy and
exceptions but leaves them untouched. The review report identifies any migration
edits needed; it never presents a replacement that silently drops exceptions or
approves observed edges. Apply reviewed changes through normal source control.
Rollback selects the original configuration.

## 5. Severity, exceptions, and exit status

Maintain separate concepts: a policy decision, diagnostic severity, explicit
exception evidence, analysis completeness, and process failure threshold. A
warning remains a forbidden edge when the rule forbids it. An exemption is a
matched, reason-bearing exception, not merely reduced severity.

Propose error and warning severities for rule violations, with a default failure
threshold of error. A stricter warning threshold fails on either. Existing
violations retain error severity and current exit behaviour unless an explicit
new configuration requests a staged rollout. Do not introduce an implicit
catch-all downgrade or an automatically generated baseline.

| Situation | Required behaviour |
| --- | --- |
| Invalid configuration, unreadable input, or failed analysis | Non-zero status; severity cannot turn an operational failure into success. Preserve documented input-error status 2. |
| Forbidden edge meeting the configured threshold | Check fails with policy status 1. |
| Forbidden warning below an explicit threshold | Gate may pass, but the report retains the violation and states that policy compliance failed. |
| Unresolved or unclassified internal edge in strict mode | Gate fails regardless of ordinary rule-severity downgrades, consistent with P0. |
| Matched documented exception | Preserve its reason and distinguish exemption from permission. |
| Unmatched exception with the existing failure option | Preserve status 2 and its existing diagnostic contract. |
| Discovery or explicit observation | Successful execution does not imply compliant architecture; report unevaluated scope. |

_Table 2: Failure thresholds do not redefine architectural truth._

The versioned report records `policy_ok`, `gate_passed`, and coverage/scope
separately. Document how legacy `ok` projects policy compliance; do not silently
relabel it as threshold success. P0's accepted semantics take precedence where
uncertainty affects that projection. Test stdout, stderr, payload, and exit code
together so scripts can distinguish these cases.

Internal coverage relaxations, where P0 permits explicit configuration, remain
separate from ordinary warning levels and visibly reduce the scope claim. Error
handling, unknown configuration keys, and invalid exception reasons remain hard
failures.

## 6. Migration and acceptance

Use the two P1 migration-derived fixtures for the whole adoption journey:

1. Inventory current roots, dependencies, unknowns, and documented exceptions.
2. Preview a candidate and resolve ambiguous mappings explicitly.
3. Review internal rules and choose external defaults without copying observed
   edges into permission lists.
4. Check the selected candidate, fix violations or document narrowly justified
   exceptions, and introduce explicit severity only where needed.
5. Enforce the selected threshold, tighten staged warnings, and check stale
   exceptions. Verify that returning to the original configuration restores its
   previous behaviour.

Task 3.1 specifies/evaluates external policy, 3.2 validates candidate
generation, and 3.3 separates severity/gate semantics and records adoption
evidence. The [roadmap](roadmap.md) maps each task to dependencies and design
sections.

Acceptance requires both complete journeys, deterministic valid candidate TOML,
no-clobber and race tests, preserved input bytes, explicit unknown roots, all
external decision-table combinations, and the exit-status matrix. Add cases for
legacy/new conflicts, standard-library shadowing, a newly introduced external
dependency, and a previously unseen internal subtree. Retain the full P1 suite
and P2 cross-view consistency checks.

Update the configuration reference, CLI help, users' guide, and migration notes
only when the corresponding capability ships. Accept any binding semantic change
through an ADR rather than changing ADR 001 indirectly.

## 7. Alternatives, risks, and continuation

Reject generating an allowlist from all current edges: it legitimizes exactly
the drift the checker should expose. Reject in-place TOML editing for the first
iteration: comment preservation and conflict handling add risk without being
necessary for candidate review. Reject file-wide suppressions or a severity-only
approach to uncertainty because they obscure what was actually checked.

The principal risks are configuration complexity, false confidence from an
observational run, and incompatibility with existing automation. Address them
through explicit modes, versioned reports, restrictive candidate review, and
legacy behavioural fixtures. Reuse bounded runner and cache controls from RFC
001; no additional hosted infrastructure or periodic scans are necessary.

Before accepting this RFC, agree the exact external configuration grammar,
severity/threshold option names, standard-library target declaration, and
candidate serializer. Before P3 release, repeat the evidence review against
available alternatives. Continue only where conformance, explanations, and
adoption evidence justify the maintenance burden; integration or retirement
remains an acceptable evidence-based outcome.
