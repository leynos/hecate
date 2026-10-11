# Adopt the nose code-duplication gate in Hecate

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: APPROVED

## Purpose / big picture

Hecate is a small, sharp tool: 11 production modules under `hecate/` that
enforce import boundaries by walking the standard library abstract syntax tree
(AST). Small tools accrete copy-paste. Two guard clauses that began as a
deliberate parallel slowly drift, and the drift is invisible to Ruff, Pylint,
Skylos, and the type checker, because every one of those tools judges a module
alone.

After this change a contributor who runs `make lint` also runs a blocking
code-duplication gate. The gate executes the pinned `nose` detector over
`hecate/`, normalizes its JSON report, removes families covered by reasoned
exceptions in `[tool.duplication_gate]`, and fails when an unsuppressed family
remains. A contributor who decides a family is an intentional parallel records
that decision with `make duplication-allow FIRST='...' REASON='...'`, which
proves the entry actually covers every location of every matching family, and
which serializes and fences its read-modify-write of `pyproject.toml` so
concurrent invocations cannot lose an entry.

The observable end state is:

1. `make duplication` exits 0 on a clean tree and prints either a clean
   summary or the allowed families it silenced.
2. A duplicated block planted in `hecate/` makes `make duplication` exit 1 and
   name the family with repository-relative `path:start-end` spans.
3. A `[[tool.duplication_gate.allow]]` entry whose keys cover that family
   exactly makes the gate exit 0 again, while an extra, unlisted member of the
   same family makes it exit 1 again.
4. `make lint` runs all of that, after Ruff, Pylint, and Skylos, without
   weakening any of them.

The objective is to remove unjustified repeated logic and keep intentional
parallels explicitly reviewable, not to achieve a low duplication count
through indiscriminate abstraction or suppression.

## Constraints

- The five gate and support modules live in `scripts/`, beside
  `scripts/generate_typos_config.py` and `scripts/typos_rollout.py`, because
  hecate already keeps repository tooling there and `scripts/` is not a
  distributed package. They must not become part of the `hecate` distribution.
- `[project].requires-python` stays `>=3.14`. The application dependency list
  stays `["cyclopts"]`. The gate must never require installing, importing,
  building, or starting the application: it talks to a subprocess and to TOML.
- The gate runs the pinned `nose` binary at version 0.20.0 from
  `https://github.com/corca-ai/nose`. Compilation fallback is prohibited. No
  `cargo install`, no floating `latest` installer, no curl-to-shell bootstrap,
  no third-party binary mirror.
- The scan roots are `["hecate"]`. `tests/`, `scripts/`, and `scripts/tests/`
  are outside the scan and that omission is documented with its reason.
- Exit codes are fixed: 0 clean or fully allowed, 1 unsuppressed families, 2
  configuration or tool-execution error. Every failure mode that could
  otherwise look like "no findings" must fail closed.
- An allow entry matches a family only when *every* location of that family
  matches one of the entry's keys. A new member outside the entry's keys must
  block. Keys are never line numbers or detector identifiers.
- The allow-entry shape is exactly one of `unit = "path[::name]"` or
  `members = ["path[::name]", ...]` (at least two), plus a non-blank `reason`.
- `pyproject.toml` is edited by `tomlkit` so existing comments and unrelated
  configuration survive byte-for-byte, and the edit is atomic under an advisory
  sidecar lock.
- Every duplicated extraction goes to the smallest coherent helper at the
  correct architectural layer. No generic utility module, no inheritance
  hierarchy, no boolean-mode helper, no compatibility shim or forwarding
  wrapper for a pre-1.0 private API.
- No file from `benchmarks/duplication/**`, no `benchmarks/score_support.py`,
  no dead-code benchmark change, no `tests/test_duplication_benchmark*.py`, no
  benchmark report, and no benchmarking continuous integration (CI) job is
  copied into this repository.
- The gate does not claim episodic's precision, recall, or timings.

## Tolerances (exception triggers)

- Scope: if the change needs more than 40 files or 2500 net lines, stop and
  escalate.
- Interface: if `[project].requires-python`, the `hecate` package's public
  surface, or its runtime dependencies must change, stop and escalate.
- Dependencies: if the gate needs a new *runtime* dependency, stop and
  escalate. Gate-only tooling dependencies are in scope.
- Adjudication: if more than six allow entries are needed to reach a green
  gate, stop and escalate; a count that high suggests the roots or the size
  floor are wrong rather than that six parallels are intentional.
- Ranking: if the number of reported families approaches the `top = 30` bound,
  stop and escalate rather than raising the bound or lowering the size floor.
- Iterations: if a single gate failure survives three fix attempts, stop and
  escalate.
- Provenance: if the pinned binary cannot be provisioned from a verified
  release artefact, stop and escalate rather than compiling from source.

## Risks

- Risk: `nose` 0.20.0 may emit no `name` for hecate's findings, so `::name`
  keys cannot be used and every exception must be a path glob. Severity: low
  Likelihood: high Mitigation: confirmed during reconnaissance; document it in
  the developer guide and in the allow-list module so the syntax is not
  advertised as usable when it is not.
- Risk: `top = 30` is a ranking bound, not a proof of absence. A family below
  the cutoff is not enforced. Severity: medium Likelihood: high Mitigation:
  document the bound honestly; keep the stale-entry diagnostic phrased as
  "unmatched in this scan"; verify with a widened scan before deleting an
  entry.
- Risk: `fcntl.flock` and POSIX directory syncing are unavailable on native
  Windows. Severity: low Likelihood: low Mitigation: document a POSIX or
  Windows Subsystem for Linux (WSL) developer workflow and a Linux CI gate; do
  not claim Windows support.
- Risk: cargo-binstall's Git source mode may fall back to a source build on a
  platform with no published artefact. Severity: medium Likelihood: low
  Mitigation: `--disable-strategies compile,quick-install` makes the fallback a
  hard provisioning error.
- Risk: adding a blocking gate to `make lint` could break the existing green
  pipeline if the scan is misconfigured. Severity: medium Likelihood: medium
  Mitigation: land the gate with the adjudicated allow list in the same commit
  and run the real binary locally before pushing.
- Risk: the `scripts/` helper tests use Python 3.14-only syntax and could be
  swept into the application test run by the wrong interpreter. Severity:
  medium Likelihood: low Mitigation: keep them under `scripts/tests/`, which
  the existing Ruff `extend-exclude` and the test contract already treat as a
  separate tooling area, and give them their own interpreter contract.

## Progress

- [x] (2026-10-11 15:06Z) Reconnaissance: identify the target repository,
  confirm no pre-existing nose configuration, confirm `hecate` is the
  production root, read the reference implementation at the pinned revision.
- [x] (2026-10-11 15:07Z) Provision and verify the pinned detector at
  `.tools/nose/nose`; confirm `nose 0.20.0`.
- [x] (2026-10-11 15:10Z) Establish the real duplication surface: two families
  at `min-size 24` on the widened surface, both in `hecate/config.py`.
- [ ] Write this ExecPlan.
- [ ] Port `scripts/nose_schema.py`, `scripts/nose_detector.py`,
  `scripts/atomic_write.py`, `scripts/duplication_allowlist.py`, and
  `scripts/duplication_gate.py`.
- [ ] Add `[tool.nose]` and `[tool.duplication_gate]` to `pyproject.toml`.
- [ ] Add the Makefile pins and the `install-nose`, `duplication`,
  `duplication-test`, and `duplication-allow` targets; wire `lint`.
- [ ] Add the CI cache and install steps.
- [ ] Ignore `.tools/` and the gate lock file.
- [ ] Port and adapt the focused tooling tests into `scripts/tests/`.
- [ ] Extend `tests/test_toolchain_contract.py` with the nose pin contracts.
- [ ] Adjudicate hecate's families and land the extractions plus the allow
  entries.
- [ ] Document in the developer guide, `AGENTS.md`, the configuration
  reference, and a new architecture decision record (ADR).
- [ ] Demonstrate the gate against the real binary in a disposable workspace.
- [ ] Run the commit gates and open the draft pull request.

## Surprises & discoveries

- Observation: `nose query --root hecate --min-size 24 --format json` returns
  an empty `families` array in about 20 ms, which reads as a broken scan.
  Evidence: `nose stats hecate` reports 11 files and 3960 intermediate-language
  nodes with 0 raw, so coverage is complete; probes at lower `--min-size` do
  return families. Impact: the default surface hides every finding, so
  `surface = "all"` is load-bearing rather than cosmetic. The Empty-result trap
  is worth a line in the developer guide.
- Observation: `--surface` is not a flag. `--surface all` is rejected; the
  widened surface is selected by a bare `all` term in the query.
  Evidence: every iteration of a `--surface all` sweep failed to parse.
  Impact: the wrapper must build the argument vector with the bare term.
- Observation: nose supplies no `name` and no `kind` for any hecate finding.
  Evidence: the JSON report has `name: null` on every region. Impact: every
  hecate exception is a path or path-glob key; `::name` is unusable here and
  the documentation must say so.
- Observation: hecate has two files numbered `adr-002-`.
  Evidence: `docs/adr-002-adopt-the-shared-cv005-contract-library.md` and
  `docs/adr-002-four-tier-python-linting.md` coexist. Impact: the next free
  identifier is `adr-003`, which sidesteps the existing collision rather than
  extending it, and the collision is noted in the pull request rather than
  silently fixed.
- Observation: `.tools/` is not currently ignored by Git.
  Evidence: `git check-ignore -v .tools/nose/nose` exits 1. Impact: the ignore
  entry must land with the first commit that would otherwise see the binary.

## Decision log

- Decision: record this plan at
  `docs/execplans/adopt-nose-code-deduplication.md` and commit it.
  Rationale: the operator's standing instruction prescribes
  `docs/execplans/${GIT_BRANCH_NAME##*/}.md` for plans and requires living
  documents to be updated frequently enough to survive context compaction.
  Hecate has no prior `docs/execplans/` tree, so this introduces the directory
  rather than following an existing one; that deviation is recorded here and in
  the pull request. Date/Author: 2026-10-11, implementation agent.
- Decision: status is `APPROVED` rather than `DRAFT`.
  Rationale: the work order was fully specified before implementation and the
  operator supplied standing instructions that all change requests reaching the
  agent are requirements to be actioned. The approval gate is satisfied by the
  work order itself; stalling for a separate confirmation would contradict the
  standing instruction. Date/Author: 2026-10-11, implementation agent.
- Decision: scan `roots = ["hecate"]` only.
  Rationale: that is the maintained production Python root, and it is the same
  starting point the reference adoption chose. `tests/`, `scripts/`, and
  `scripts/tests/` have their own parallel-structure reasons for existing and
  are excluded explicitly and visibly rather than by an unexplained omission.
  Date/Author: 2026-10-11, implementation agent.
- Decision: keep `mode = "syntax,semantic,near"` and `min-size = 24` unchanged
  from the starting configuration.
  Rationale: the repository has no evidence that would justify a different
  floor, and the size is nose's intermediate-language token count, not a line
  or AST-node count, so comparing it to hecate's line counts would be
  meaningless. The three channels are pinned explicitly so that removing one is
  a visible, reviewable act. Date/Author: 2026-10-11, implementation agent.
- Decision: keep `top = 30`; do not change the ranking budget.
  Rationale: the widened scan reports two families, so the budget is nowhere
  near saturation and lowering it would only reduce coverage. The budget is a
  ranking bound, not an exhaustive enumeration, and the documentation says so.
  Date/Author: 2026-10-11, implementation agent.
- Decision: reuse the tool-selection decision by reference.
  Rationale: the detector competition between nose, PyChase, and pyscn was
  settled upstream. Re-running it here would burn budget and would tempt the
  plan to claim episodic's measured precision, recall, or timings for hecate,
  which this repository has not measured. Date/Author: 2026-10-11,
  implementation agent.
- Decision: add `nose_schema.py` as a sixth module rather than folding its
  normalization into `duplication_gate.py`.
  Rationale: the reference separates report validation from orchestration, and
  hecate's pylint ceiling of 400 module lines makes a single fused module
  fragile. The decomposition also keeps the pure functions — key validation,
  glob matching, family matching — independently testable without a subprocess.
  Date/Author: 2026-10-11, implementation agent.
- Decision: number the new ADR `adr-003`.
  Rationale: `adr-001` and a duplicated `adr-002` already exist; `adr-003` is
  the next free identifier and does not extend the collision.
  Date/Author: 2026-10-11, implementation agent.

## Outcomes & retrospective

Not yet complete. Reconnaissance outcomes: the target repository is
`leynos/hecate`; it has no pre-existing `[tool.nose]`, `[tool.duplication_gate]`,
`.tools/`, `nose.toml`, `.nose.toml`, `nose.ignore.json`, or native baseline, so
nothing can silently narrow the intended scan; and the pinned detector is
provisioned and answering `nose 0.20.0`.

Lesson carried into implementation: the empty-result trap and the absent unit
names were both discovered only by querying the real binary rather than by
reading its documentation, which is why the plan requires a real-binary
demonstration rather than only injected-runner unit tests.

## Context and orientation

Hecate is published as the `hecate` Python package and exposes one console
script, `hecate = "hecate.cli:main"`. It parses each module under a configured
package root with the standard library `ast` module, resolves intra-package
imports, and reports violations of a declared group policy. The production
sources are the eleven modules directly under `hecate/`:
`__init__.py`, `checker.py`, `cli.py`, `config.py`, `config_helpers.py`,
`diagnostics.py`, `imports.py`, `output.py`, `policy.py`, `reexports.py`, and
`report.py`.

Repository tooling lives in `scripts/`. `scripts/generate_typos_config.py`,
`scripts/typos_rollout.py`, and `scripts/typos_rollout_cache.py` maintain the
shared spelling dictionary; `scripts/tests/test_typos_rollout.py` tests them.
`pyproject.toml` excludes those four files from Ruff, and
`scripts/tests/test_typos_rollout.py` asserts that every script under
`scripts/` still parses with a Python 3.13 feature version. That assertion
does not constrain the new gate modules, which are Python 3.14 tooling and
carry their own inline script metadata under a
`#!/usr/bin/env -S uv run python` shebang.

The commit gate is `make lint`, which depends on `lint-python` (Ruff over
`hecate tests`, then Pylint under a managed PyPy 3.12) and on `skylos` (a
strict production dead-code scan over `hecate`, excluding `tests`). The full
test suite is `make test`, which depends on `build`, `$(VENV_TOOLS)`,
`makeutil`, and `test-workflow-contracts`. `makeutil` is a pinned Makefile
parser; `tests/test_skylos_lint_contract.py` parses `Makefile` with it and
asserts exact variable values and recipe token sequences. Continuous
integration is `.github/workflows/ci.yml`, job `lint-test`, which runs
`make lint`.

"Duplication family" means a set of two or more code regions that nose judges
to be repeats of one another. "Surface" means how many families nose reports;
the widened surface reports every family it found rather than the ranked
default subset. "Intermediate-language token count" means nose's own
normalized token measure, which sizes a unit before ranking; it is not a line
count. "Allow entry" means one `[[tool.duplication_gate.allow]]` table in
`pyproject.toml`. "Fail closed" means that a missing binary, a timeout, a
non-zero exit, malformed JSON, or an unrecognized report shape produces exit
code 2 with a diagnostic, never an empty findings list and never a silent pass.

## Conformance basis

The upstream references are:

- Pull request: `https://github.com/leynos/episodic/pull/276`.
- Immutable merged revision:
  `d9e5ac0d254f375e2986f52d91a3b88c117c833b` in `leynos/episodic`.
- The adopted decision record: `docs/adr-021-adopt-nose-duplication-gate.md` at
  that revision is represented in this repository by
  `docs/adr-003-adopt-the-nose-duplication-gate.md`, which cites the upstream
  revision and the requirements it inherits.
- The detector: `nose` 0.20.0 from `https://github.com/corca-ai/nose`, a Rust
  binary named `nose`. It is unrelated to the Python `nose` test framework.
- This plan: `docs/execplans/adopt-nose-code-deduplication.md`.

There is no Terms of Reference and no technical design document for this
repository; this plan's `Constraints` and `Verification plan` are the governing
statement. The trace chain used by this plan is:

```plaintext
NOSE-REQ-roots  -> scripts/nose_detector.py    -> EP-M2 -> scripts/tests/test_nose_detector.py
NOSE-REQ-keys   -> scripts/duplication_allowlist.py -> EP-M2 -> scripts/tests/test_duplication_gate.py
NOSE-REQ-atomic -> scripts/atomic_write.py     -> EP-M1 -> scripts/tests/test_atomic_write.py
NOSE-REQ-pins   -> Makefile + ci.yml           -> EP-M3 -> tests/test_toolchain_contract.py
NOSE-REQ-adjud  -> hecate/config.py            -> EP-M5 -> make duplication
```

## Verification plan

This change introduces no formal theorem obligation. It does introduce
invariants over matching, ordering, persistence, and failure handling whose
violation is silent — a gate that passes when it should fail is worse than no
gate — so each is paired with a method that can actually fail.

Obligation `INV-KEYS`. An allow entry matches a family if and only if every
location of the family matches at least one of the entry's keys, and every key
of the entry is well formed. Method: parameterized tests over the finite
partitions (one key, two keys, glob boundary, `::name` present, `::name` absent
from the report, malformed glob, empty members, both `unit` and `members` set,
neither set, blank reason). Rationale: the input space is small and the
partitions are enumerable, so a property test would add cost without adding
coverage. Domain: `PurePosixPath.full_match` semantics, repository-relative
POSIX paths, and the optional `::name` suffix. Artefact:
`scripts/tests/test_duplication_gate.py`. Evidence:
`uv run --python 3.14 --with pytest --with hypothesis pytest scripts/tests/test_duplication_gate.py`
passes; a negative control removes the "every location" conjunct and the
whole-family test must fail. Non-vacuity: the fixture families carry two and
three locations, and at least one case has a member outside the entry's keys.

Obligation `INV-ORDER`. Normalized gate output, and the partition into
blocking, allowed, and stale entries, is a deterministic function of the report
and the allow list, independent of dictionary iteration order. Method:
property test with generated family and entry sequences, asserting
`partition(findings, entries)` is invariant under a shuffle of its inputs and
that repeated normalization of one report is byte-identical. Rationale:
ordering is a range property over generated sequences, which is exactly what a
property test is for. Domain: sequences of 0 to 8 families with 1 to 4
locations each. Artefact: `scripts/tests/test_duplication_gate_properties.py`.
Evidence: the generated suite passes and a seeded mutation that sorts by a
non-total key is rejected. Non-vacuity: the generator is asserted to produce at
least one multi-family sequence per run, and a fixed counterexample is pinned
as a regression case.

Obligation `INV-FAILCLOSED`. Every detector failure mode yields exit code 2 and
a diagnostic naming the cause; none yields exit code 0 or an empty finding
list. Method: parameterized tests with injected command runners that raise, time
out, exit non-zero, emit truncated JSON, emit a JSON array instead of an
object, emit a report with an unknown `schema_version`, and emit a family
missing a required field. Rationale: these are distinct finite partitions with
distinct handling. Domain: the runner boundary, exercised without downloading
nose. Artefact: `scripts/tests/test_nose_detector.py`. Evidence: each case
asserts the specific exit code and that the message names the failure; the
negative control is a valid report, which must yield exit code 0.

Obligation `INV-ATOMIC`. A read-modify-write of `pyproject.toml` through the
allow helper is atomic under the sidecar lock, preserves unrelated content and
comments, is idempotent for the same target including reordered members, and
leaves no temporary file behind on failure. Method: concurrent multi-process
test driving the real CLI against a temporary copy of the repository
configuration, plus parameterized tests over the member sets. Rationale:
interleaving is the property under test and only real concurrency exposes it.
Domain: 2 to 8 concurrent processes, member sets of size one and three.
Artefact: `scripts/tests/test_duplication_gate_persistence.py`. Evidence: after
all processes finish, the file parses and contains exactly the union of the
requested entries; a negative control removes the lock and the same test must
lose at least one entry. Non-vacuity: the test asserts that the processes
actually overlapped by recording start and end timestamps.

Obligation `INV-PINS`. The pinned nose version is identical in the Makefile,
the CI workflow environment, and `[tool.nose] version`; every scan command
enforces the version before running; the installation command disables the
compile and quick-install strategies. Method: contract test parsing the
Makefile with makeutil and the workflow with PyYAML, mirroring the existing
Skylos contract. Rationale: the invariant is about configuration agreement
across files that no type checker sees. Domain: three files and their literal
values. Artefact: `tests/test_toolchain_contract.py`. Evidence: the contract
passes; the negative control changes one of the three versions and the contract
must fail.

Obligation `INV-REAL`. The gate behaves as specified against the real pinned
binary, not only against injected runners. Method: disposable-workspace
integration demonstration. Rationale: this is the only method that exercises
argument construction, working-directory handling, report shape, and ranking
behaviour together. Domain: a temporary workspace with a small unsaturated
Python package. Artefact: the transcript recorded in this plan's `Artefacts and
notes`. Evidence: a clean run exits 0; a planted substantial clone exits 1 and
names the family; a narrow reasoned exception makes it exit 0; an added
out-of-scope member makes it exit 1 again; three consecutive runs produce
byte-identical normalized output. Non-vacuity: the workspace is intentionally
small so the `top = 30` bound cannot hide the canary, and the planted clone is
asserted to exceed the size floor before the gate is invoked.

External axioms, not verified here: nose's own ranking, its tokenization, and
its JSON schema are treated as documented interfaces. The contract that hecate
owns and does verify is its own use of those interfaces — the argument vector
it constructs, the working directory it sets, the fields it reads, and its
behavior when a field is absent.

## Plan of work

Stage A — reconnaissance, complete. Identify the repository, the production
root, the existing tooling conventions, and the real duplication surface;
provision and verify the pinned binary.

Stage B — the tooling modules. Write the focused tests for each module first,
then the module. In `scripts/nose_schema.py`, define the normalized `Finding`
and `Region` records, the `GateConfigError` and `GateExecutionError` types, the
report-schema version this adoption supports, and the normalization of a raw
JSON document into families with the invariant checks that make an unexpected
shape a hard error. In `scripts/nose_detector.py`, define `PYPROJECT`, the
`[tool.nose]` settings record with its `load_settings` reader and its version
agreement check, and `run_detector`, which builds the argument vector, runs the
pinned binary with an explicit repository working directory, enforces a bounded
timeout, and normalizes through the schema module. In `scripts/atomic_write.py`,
port the neutral atomic-write primitive unchanged apart from attribution. In
`scripts/duplication_allowlist.py`, define `AllowEntry`, key validation, the
whole-family matcher, the TOML reader, and the locked idempotent writer. In
`scripts/duplication_gate.py`, define the Cyclopts application with the
`check` and `allow` commands, the `partition_findings` function, and the exit
codes.

Stage C — repository integration. Add `[tool.nose]` and an empty
`[tool.duplication_gate]` to `pyproject.toml`. Add the Makefile pins and the
four targets, and make `lint` depend on the gate. Add the CI cache and install
steps. Ignore `.tools/` and the gate lock file. Extend the toolchain contract
test.

Stage D — adjudication. Run the configured gate, inspect every blocking family
and its callers, and classify it. For genuine duplication write the focused
test first, then extract the smallest coherent helper at the right layer and
update the callers, then rerun the gate. For an intentional parallel, record a
reasoned entry with `make duplication-allow`. Rerun after every change, because
a lower-ranked family can enter the surface once a higher-ranked one is
resolved.

Stage E — documentation and delivery. Add the architecture decision record,
extend the developer guide and the configuration reference, record the
adjudication in this plan, run the disposable-workspace demonstration, run the
commit gates, and open the draft pull request.

## Milestones and plateaus

- Identifier and outcome: `EP-M1`, the five tooling modules exist under
  `scripts/` with their focused tests and no repository integration yet.
  Requirements and gaps: `NOSE-REQ-keys`, `NOSE-REQ-atomic`. Acceptance
  evidence: `scripts/tests/` passes and the modules import cleanly. Conformance
  check: no application file changes; no dependency change; no persisted-format
  change beyond the new TOML tables; trace links current. Recovery: the
  directory is additive, so reverting it is a file deletion. Remaining gaps:
  nothing runs the gate. Compatibility decision: none.
- Identifier and outcome: `EP-M2`, the gate is runnable by hand —
  `pyproject.toml` carries `[tool.nose]` and `[tool.duplication_gate]`, and the
  detector, schema, allow-list, and gate modules agree on the contracts.
  Requirements and gaps: `NOSE-REQ-roots`, `NOSE-REQ-keys`. Acceptance
  evidence: `make duplication` runs and the focused tests pass. Conformance
  check: roots validated to exist; no application change; no new interface
  outside `scripts/`. Recovery: revert the `pyproject.toml` tables and the
  script directory. Remaining gaps: no CI, no lint wiring. Compatibility
  decision: none.
- Identifier and outcome: `EP-M3`, provisioning is reproducible and gated.
  `make install-nose`, the CI cache and install steps, the ignore entries, and
  the pin contract all exist and agree. Requirements and gaps: `NOSE-REQ-pins`.
  Acceptance evidence: `tests/test_toolchain_contract.py` passes; a second
  `make install-nose` is a no-op that verifies the installed version.
  Conformance check: existing lint stages preserved; no dependency change; no
  trust-boundary change beyond the pinned upstream release. Recovery: the
  targets and CI steps are additive. Remaining gaps: adjudication not done.
  Compatibility decision: none.
- Identifier and outcome: `EP-M4`, `make lint` blocks on unjustified
  duplication with an adjudicated repository. Requirements and gaps:
  `NOSE-REQ-adjud`. Acceptance evidence: `make duplication` exits 0; the
  demonstration transcript shows the four-state sequence. Conformance check:
  every allow entry has a reason naming the boundary an extraction would
  wrongly couple; no entry uses a repository-wide wildcard; trace links
  current. Recovery: each extraction is a separate atomic commit. Remaining
  gaps: documentation. Compatibility decision: none — the extraction candidates
  are pre-1.0 private functions, so callers are updated directly rather than
  any shim being introduced.
- Identifier and outcome: `EP-M5`, adopted and reviewable. Requirements and
  gaps: all of the above. Acceptance evidence: the draft pull request with the
  ADR, the updated guides, and the recorded gate runs. Conformance check: no
  benchmark asset copied; no unrelated migration; no copied episodic path;
  Python floor and dependencies unchanged. Recovery: the pull request is a
  draft and is not merged. Remaining gaps: none in scope.

## Concrete steps

All commands run from the worktree root.

Write the tooling tests first and confirm they fail:

```plaintext
uv run --python 3.14 --with pytest --with hypothesis pytest scripts/tests -q
```

Expected: failures naming the missing modules, which is the red stage.

Then add the modules and rerun the same command. Expected: all pass.

Verify the pins and provisioning:

```plaintext
make install-nose
.tools/nose/nose --version
```

Expected transcript:

```plaintext
nose 0.20.0
```

Run the gate:

```plaintext
make duplication
```

Expected on a clean, fully adjudicated tree:

```plaintext
duplication gate: 0 unsuppressed families
```

Run the focused gate suite:

```plaintext
make duplication-test
```

Expected: the tooling tests pass.

Record an exception:

```plaintext
make duplication-allow FIRST='hecate/config.py' REASON='Parallel TOML validation arms, see ADR-003'
```

Expected: the entry is appended to `pyproject.toml` with its reason intact, and
a second identical invocation changes nothing.

Full gates, run sequentially, each captured to a log:

```plaintext
make check-fmt 2>&1 | tee /tmp/check-fmt-hecate-adopt-nose-code-deduplication.out
make lint      2>&1 | tee /tmp/lint-hecate-adopt-nose-code-deduplication.out
make typecheck 2>&1 | tee /tmp/typecheck-hecate-adopt-nose-code-deduplication.out
make test      2>&1 | tee /tmp/test-hecate-adopt-nose-code-deduplication.out
make markdownlint 2>&1 | tee /tmp/markdownlint-hecate-adopt-nose-code-deduplication.out
make nixie     2>&1 | tee /tmp/nixie-hecate-adopt-nose-code-deduplication.out
```

## Validation and acceptance

Acceptance is behavioural. Run `make duplication` and observe exit code 0 on a
clean tree, exit code 1 with a planted clone, exit code 0 again once a narrow
reasoned exception covers that family exactly, and exit code 1 again once an
extra out-of-scope member is added. Run it three times and compare the
normalized output byte for byte. Run `make duplication-allow` twice with the
same arguments and confirm the file changes once. Run `make duplication-allow`
with a value containing spaces, single quotes, double quotes, a dollar sign,
and a command-substitution-looking string, and confirm the reason stored in
`pyproject.toml` is byte-identical to the value supplied.

The new tooling tests fail before the modules exist and pass after. The
existing application tests, formatting, lint, and type checks are unchanged in
outcome. The `scripts/` helper tests run under the tooling interpreter and are
not collected by the application test run.

Quality criteria: `make check-fmt`, `make lint`, `make typecheck`, `make test`,
`make markdownlint`, and `make nixie` all pass; the disposable-workspace
demonstration transcript is recorded here; no benchmark asset, unrelated
migration, or copied episodic path appears in the diff.

## Idempotence and recovery

`make install-nose` is idempotent: when the installed binary already reports
the configured version it exits without reinstalling. The allow helper is
idempotent for an identical target, including a reordered member list. Nothing
in the plan deletes tracked files. The tooling directory is additive, so
reverting a milestone is a deletion of new files plus a revert of the
`pyproject.toml`, Makefile, workflow, and ignore edits, each of which is a small
atomic commit. Planted clones and temporary exceptions exist only inside a
temporary directory and are removed before the work is committed; the plan
requires verifying that no planted clone or temporary exception remains in the
tree.

## Artefacts and notes

Reconnaissance transcripts:

```plaintext
$ nose stats hecate
11 files, 3960 IL nodes, 0 raw

$ nose query --root hecate all --mode syntax,semantic,near --min-size 24 --top 30 --format json
{"families": [ ... 2 families, both under hecate/config.py ... ]}
```

The demonstration transcript is recorded here once Stage E runs.

## Interfaces and dependencies

In `scripts/nose_schema.py`:

```python
class GateConfigError(Exception): ...
class GateExecutionError(Exception): ...

@dc.dataclass(frozen=True, slots=True)
class Region:
    path: str
    start: int
    end: int
    name: str | None

@dc.dataclass(frozen=True, slots=True)
class Finding:
    regions: tuple[Region, ...]
    witness: str
    value: float
```

In `scripts/nose_detector.py`:

```python
PYPROJECT: Path

@dc.dataclass(frozen=True, slots=True)
class NoseSettings:
    version: str
    roots: tuple[str, ...]
    mode: str
    min_size: int
    surface: str
    top: int

def load_settings(path: Path = PYPROJECT) -> NoseSettings: ...
def run_detector(
    settings: NoseSettings,
    *,
    runner: CommandRunner = _run_command,
    repository: Path = PYPROJECT.parent,
) -> list[Finding]: ...
```

In `scripts/duplication_allowlist.py`:

```python
@dc.dataclass(frozen=True, slots=True)
class AllowEntry:
    keys: tuple[str, ...]
    reason: str
    def matches(self, finding: Finding) -> bool: ...

def validate_key(key: str) -> None: ...
def load_allowlist(path: Path = PYPROJECT) -> tuple[AllowEntry, ...]: ...
def append_allow_entry(entry: AllowEntry, path: Path = PYPROJECT) -> bool: ...
```

In `scripts/duplication_gate.py`:

```python
def partition_findings(
    findings: cabc.Sequence[Finding],
    allowlist: cabc.Sequence[AllowEntry],
) -> tuple[list[Finding], list[Finding], list[AllowEntry]]: ...

def main() -> int: ...
```

`tomlkit` is the only gate-only dependency added, and it is declared in the
inline script metadata alongside `cyclopts`, never in
`[project].dependencies`.

## Revision note

Initial draft, 2026-10-11. Establishes the plan, records the reconnaissance
findings and the adjudication policy, and fixes the milestone boundaries. No
remaining work was re-scoped.
