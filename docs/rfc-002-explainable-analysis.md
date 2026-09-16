# RFC 002: Shared analysis records and explainable reports

## Status and scope

Proposed, 2026-09-16. Implements the design for [roadmap phase
2](roadmap.md#2-p2-expose-explainable-analysis), ideas I3 and I4. P0 issue #104
and the P1 continuation gate precede authoritative rollout. Commands and record
names below are proposed interfaces, not current features.

## 1. Context and design signposts

[ArchitectureCheckResult](../hecate/checker.py) currently retains violations,
ignored imports, and unmatched ignores. [Output rendering](../hecate/output.py)
serializes `ok` and `violations`, adding `ignored` on request. The
[CLI](../hecate/cli.py) documents exit statuses 0, 1, and 2. Reports must not
silently replace these interfaces or repeat import analysis in each command.

Build on [imports](../hecate/imports.py), [re-export
expansion](../hecate/reexports.py), and [policy
evaluation](../hecate/policy.py). Reuse the outcome model accepted for #104. Do
not introduce a competing resolver or move policy into renderers.

## 2. Goals and boundaries

Retain enough evidence to answer what was imported, where it came from, which
policy applied, and what analysis could not establish. Supply a read-only graph
without requiring a policy and an explanation without proposing a source edit.

Preserve [ADR 001](adr-001-stdlib-ast-import-engine.md): no project execution,
no dynamic inference claim, no new language engine, and no general plugin
system. JSON, Graphviz DOT, text, and GitHub annotations are sufficient;
rendering SVG or running a hosted dashboard is out of scope.

## 3. Analysis contract

Introduce immutable records through one source-to-check vertical slice, then
expand across the P1 corpus. Proposed responsibilities are:

| Record | Required evidence |
| --- | --- |
| Import occurrence | Importing module, normalized source path, source span, import form, requested module/names, and aliases. |
| Resolution | Occurrence identity, direct target, derived origins, provenance links, and resolved/partial/unresolved status with reasons. |
| Classification | Internal/external/standard-library/unknown ownership and source/target groups, retaining unclassified endpoints. |
| Policy assessment | Edge identity, matched rule, permitted/forbidden/exempted/not-evaluated outcome, and a separate diagnostic severity. |
| Exception evidence | Matched ignore identity, required reason, and the exact assessed edge; unmatched entries remain distinct diagnostics. |
| Analysis report | Schema version, source/config fingerprints, scope and limitations, ordered records, coverage counts, and policy/gate summaries. |

_Table 1: Proposed record boundaries and retained evidence._

Resolution, classification, severity, and policy truth are different axes.
Unresolved or unclassified edges must not become permitted through a default
enum value. Partial resolution retains both known origins and uncertainty. No
policy supplied means `not_evaluated`, not implicit permission.

Count source occurrences separately from derived origin edges. Each occurrence
belongs to one declared resolution bucket; origins can fan out. State how
policy-assessment counts relate to edges and report unclassified endpoints
separately. Excluded files and external checking disabled by configuration
remain visible in scope metadata. An empty or wholly excluded scan must not
claim comprehensive coverage.

The report describes statically observed import syntax and declared source
scope. It cannot certify absence of arbitrary dynamic dependencies. Preserve
unsupported constructs as limitations wherever detection is possible.

## 4. Provenance, identity, and architecture

Keep direct imports and symbol-origin expansion as distinct relationships. Store
graph links rather than enumerating every possible path. Resolve cycles with
explicit visited state or fixed-point logic; render a deterministic
representative chain and retain access to the underlying links. Truncation or
resource limits produce an explicit partial result, never a silently complete
report.

Use normalized root-relative paths and stable structural tuples for occurrence
and edge identifiers. Specify a deterministic digest encoding if identifiers
need compact strings; do not use Python's process-randomized hash. Stability
means repeatability for unchanged inputs, not immunity to source edits. Separate
nondeterministic runtime metrics from reproducible semantic payloads.

The analysis entry point accepts source roots independently of architecture
policy. A policy evaluator consumes records; commands consume the evaluator's
result; renderers do no filesystem traversal or policy matching. P0 may already
supply parts of this separation. Extract only the missing responsibilities.
Retain `check_architecture` and its legacy projection while adding the richer
internal result, with compatibility tests at each step.

Do not broaden symbol-origin tracking into indiscriminate transitive bans. An
origin edge explains the requested symbol's provenance. It does not imply that
every dependency reachable from its implementation is forbidden.

## 5. Command and output contracts

The following syntax is proposed and requires behavioural tests and help text
when implemented:

```bash
hecate analyze --package app --root src/app --format json
hecate analyze --config pyproject.toml --format dot
hecate explain --config pyproject.toml --source src/app/domain/service.py --line 12
hecate report external --config pyproject.toml --format json
hecate check --format github
hecate check --format report-json
```

`analyze` accepts roots without groups, and uses configured policy only when
supplied. Source selection and exclusions are identical to checking. DOT labels
distinguish direct and origin edges and retain unknown/unclassified nodes. A
default view must not hide these nodes to make a graph look cleaner. No Graphviz
executable is required to emit DOT.

`explain` accepts a source selector or report edge ID, lists multiple matches
rather than choosing arbitrarily, and reports missing matches explicitly. It
shows the original import, origin evidence or uncertainty, matched group order
and rule, exception reason, severity, and gate effect. It must not invent an
architectural repair or recommend a wider permission automatically.

`report external` groups observed Python module prefixes, importing groups,
source sites, and counts. It reports unknown ownership and deliberately skipped
checking. It is not an installed-distribution or vulnerability report, and it
does not map import names to package-manager names by guesswork.

Keep legacy `check --format json` intact in shape except for explicitly reviewed
P0 semantic corrections. Add the richer versioned document through
`report-json`; `analyze --format json` uses the same report schema. Record
`schema_version`, required fields, ordering, null/unknown meaning, and reader
behaviour for unknown fields. Breaking schema changes require a new version.

Machine-readable stdout contains only the selected document. Operational
messages go to stderr. Discovery success means analysis completed, not that
policy passed; the report makes this distinction explicit. Check retains its
existing exit meanings, including status 2 for invalid input and the existing
unmatched-ignore option. P3 extends gate configuration explicitly rather than
changing these defaults as part of P2.

## 6. CI safety and resource bounds

GitHub annotations are a renderer over diagnostics, not a second checker. Follow
GitHub's workflow-command protocol.[^1] Test data/property escaping for percent
signs, commas, colons, carriage returns, and newlines, with appropriate rules
for each field. Treat source-derived paths and messages as untrusted. Normalize
repository-relative paths, validate line/column bounds, and avoid absolute host
paths or source contents that could expose secrets.

An annotation does not determine the process exit status. Preserve status
handling even when output limits truncate annotations. Emit a deterministic
summary with omitted counts; the full report remains available without an
unbounded CI log. No GitHub token, network request, or shell interpolation is
necessary for rendering.

Use P1 measurements to review graph memory and runtime changes. Bound graph
traversal, displayed chains, and output volume. Reuse parsed/indexed facts
within one invocation where practical; persistent caches and daemons require
separate evidence and are not prerequisites.

## 7. Rollout, alternatives, and acceptance

Tasks 2.1.1–2.1.3 deliver the vertical slice and report contract; 2.2.1–2.2.3
add views; 2.3.1–2.3.2 validate CI and release compatibility. The
[roadmap](roadmap.md) owns their dependencies and state.

Reject a renderer-specific graph because it would duplicate resolution and lose
uncertainty. Reject a whole-engine rewrite because a direct-import slice can
prove the contract first. Defer a generalized query language and persistent
analysis database until real consumers demonstrate their necessity.

Acceptance requires all P1 cases, cross-view parity, count reconciliation, cycle
termination, repeatable serialization, legacy command snapshots, escaping
adversarial cases, and source-layout cases. Review source-span conventions and
schema evolution before publishing the report format. Record accepted changes to
binding invariants in an ADR and update the users' guide only as features ship.
Reports must not erase reason-bearing exceptions or P0 coverage failures.

[^1]: GitHub documentation, [workflow commands for GitHub
    Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands).
