# Make Ruff preview-rule adoption explicit and migrate the lint blockers exposed by Dependabot #129

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: IN PROGRESS.

Issue: <https://github.com/leynos/hecate/issues/140>

## Purpose / big picture

Hecate's Ruff configuration sets `preview = true` in `[tool.ruff]` and selects
whole prefixes such as `D`, `RUF`, `S`, `E`, `FURB`, and `PLR`. With preview
enabled, a prefix is not a fixed set of rules: it is "every rule in that
prefix, including the ones upstream is still prototyping". Ruff 0.15.13 was the
reviewed version and enabled 673 rules. Ruff 0.16.9 enables 682, adding `D421`
and nine others without any edit to `pyproject.toml`. Ruff 0.17.3 adds `UP052`
again. The dependency update is therefore not a neutral tooling bump: it
silently acquires lint policy that no commit in this repository reviewed.

Dependabot pull requests #129 (closed) and #176 (open) demonstrate the
consequence. Both install, format, spell-check, and Markdown-lint cleanly, then
fail `uv run ruff check hecate tests` with a set of diagnostics the source has
never seen. Issue #140 asks for a systemic repair: make preview adoption
explicit and reviewable, resolve the demonstrated source blockers without
changing behaviour, prove the security-suppression scope and rationale
conventions survive the migration, and keep the Ruff resolution reproducible.

After this change a contributor can answer three questions from the repository
alone. Which preview rules does this project actually rely on? Which Ruff
binary is the gate running? And if a future Ruff release adds a new preview
rule under a prefix this project selects, will that be visible in review
instead of arriving as a surprise CI failure? The observable end state:

1. `[tool.ruff.lint]` sets `explicit-preview-rules = true` and names the
   preview codes this project has reviewed, so a new preview rule inside a
   selected prefix cannot be picked up without a visible `pyproject.toml`
   change.
2. A committed inventory plus a contract test compares the *effective*
   enabled-rule list Ruff reports for representative files with the committed
   data, so dropping a rule matters as much as adding one.
3. `make build` installs from the checked-in lockfile, and a contract test pins
   the locked Ruff version against the version the gate actually runs.
4. The `D421` property docstrings are rewritten, and `noqa` suppressions
   migrate to `ruff: ignore[...]` behind a local contract that enforces
   explicit codes, a written rationale, and no security-code broadening.
5. Ruff behaviour fixtures prove the new suppression syntax still suppresses
   its security diagnostic, still surfaces adjacent diagnostics, and still
   keeps another tool's pragma on a shared line.

## Constraints

- No runtime behaviour change. `ArchitectureCheckResult.ok` keeps its exact
  truth table; only the prose of its summary line changes.
- `[project].requires-python` stays `>=3.14`, the runtime dependency list stays
  `["cyclopts"]`, and no new runtime or gate dependency is added. The Ruff
  version itself comes from the existing `dev` group and `uv.lock`.
- `preview = true` stays. This plan makes preview adoption *explicit*, not
  absent; disabling preview wholesale is prohibited by issue #140.
- No blanket `ignore` list and no broad prefix removal to make the gate green.
  Every rule that leaves the effective set must be named individually and
  reviewed.
- The checked-in `uv.lock` remains the source of truth for the gate's Ruff
  version. No hand-edited dependency update: Dependabot recreates the grouped
  update on the repaired baseline.
- No `cargo`/`uv` isolated cache. All builds use the shared default uv cache so
  concurrent agents serialize on the normal lock.
- Gates run sequentially for this worktree, per the global agent policy.
- Every new unit (inventory contract, suppression contract, behaviour fixture)
  gets unit tests; each migrated behaviour is covered before the production
  edit.

## Tolerances (exception triggers)

- Scope: if the change needs more than 30 files or 1200 net lines, stop and
  escalate. ExecPlan files are excluded from both counts, as is any generated
  inventory data file beyond 600 lines.
- Version scope: if the final dependency refresh proposes a Ruff release whose
  preview-rule delta is larger than the ones measured here (0.15.13 to 0.16.9
  added 9, 0.16.9 to 0.17.3 added 1), stop and escalate rather than absorbing
  an unbounded migration.
- Suppression: if the migration would touch a `noqa` that a tool *other* than
  Ruff parses (for example a linter requiring `noqa` beside `ruff: ignore`),
  stop and escalate for that line instead of guessing.
- Adjudication: if more than three genuinely new source defects surface beyond
  the demonstrated blockers, stop and escalate; the ticket exists for policy
  and provenance, not for an open-ended cleanup.
- Iterations: if one gate failure survives three fix attempts, stop and
  escalate.

## Risks

- Risk: enabling `explicit-preview-rules` changes the effective rule set for
  every file. On Ruff 0.15.13 it removes 106 preview rules. Any one of them may
  have been silently doing work. Severity: high, Likelihood: certain.
  Mitigation: derive the removed list by measurement, review it rule by rule,
  and re-select the ones that carry house policy. The inventory contract makes
  the review explicit and its absence visible.
- Risk: the inventory test could become a rubber stamp if regenerated without
  review. Severity: medium, Likelihood: medium. Mitigation: the test reports
  the added and removed codes and the regeneration command, and the plan
  records the reviewed delta so a reviewer can compare.
- Risk: `ruff: ignore[...]` is Ruff-specific. Another tool sharing the line
  could lose its suppression. Severity: medium, Likelihood: low. Mitigation:
  behaviour fixtures include a shared line with `# pragma: no cover`.
- Risk: the security codes `S404`/`S603`/`S607` are exactly the ones being
  migrated. Broadening one would hide a real subprocess risk. Severity: high,
  Likelihood: low. Mitigation: the contract rejects bare `noqa`, file-level
  `ruff: noqa`, and security codes in file-level or block forms, and a fixture
  proves removing the suppression restores the diagnostic.
- Risk: `uv run` re-resolves unless `--locked` is given. The CI log for #176
  shows `make build` printing `Resolved 43 packages` before installing, which
  is a silent re-resolution path. Severity: medium, Likelihood: high.
  Mitigation: `make build` uses `uv sync --locked`, and a contract test pins
  the Makefile spelling and the locked Ruff version.

## Progress

- [x] Reconnaissance: reproduce the failure on the current base with Ruff
     0.15.13, 0.16.9, and 0.17.3; capture the rule-set deltas and the effective
     enabled-rule inventory per version.
- [x] Confirm `explicit-preview-rules` is accepted by all three versions and
     measure what it removes.
- [x] Confirm the CI failure of the live grouped update (#176) is the same
     class of blocker plus `UP052`, and that `make build` re-resolves.
- [ ] Write this plan and commit it.
- [ ] Milestone 1: make preview adoption explicit on the pinned Ruff and pin
     the effective rule inventory.
- [ ] Milestone 2: pin Ruff provenance in `make build` and add the toolchain
     contract.
- [ ] Milestone 3: resolve `D421` docstrings and migrate suppressions with a
     local contract and behaviour fixtures.
- [ ] Milestone 4: refresh the grouped update, adopt the new rules explicitly,
     run every gate, and record results.
- [ ] Push, open a draft pull request, and hand the migration evidence to
     `leynos/shared-actions#588`.

## Surprises & discoveries

- On 0.15.13, `--select D421` and a `pyproject.toml` that names `D421` are both
  rejected outright with `Unknown rule selector`. The rule does not exist in
  that binary at all, so "explicit preview selection" cannot be validated by
  naming the new codes on the old binary. The explicit selection must name the
  codes that exist *at that version*, and the version bump then adds its own
  codes for review.
- `--statistics` on 0.15.13 printed nothing at all because no diagnostic was
  emitted; that is not the same as "the rule is clean".
- `explicit-preview-rules = true` is accepted by 0.15.13, 0.16.9, and 0.17.3.
  Settings dump confirms `linter.explicit_preview_rules = true`.
- `linter.rules.enabled` in `--show-settings` is identical for every Python
  file in the repository, because `per-file-ignores` are applied later. One
  inventory row is therefore sufficient for the "enabled set"; per-file
  differences belong in a separate assertion.
- The live grouped update #176 fails with 19 errors in `hecate tests`: 5
  `D421`, 12 `RUF105`, and 2 `UP052` (a rule that does not exist in 0.16.9).
  The 5 `D421` hits are all in `hecate/`; the remaining 11 `D421` hits and 16
  `RUF105` hits are in `scripts/` and only appear when `scripts` is scanned.
- `uv sync --locked` on the dependabot lockfile copy installed Ruff 0.17.3,
  confirming the lockfile is authoritative once `--locked` is in force.
- `uv lock` recomputes `revision = 5` for this `pyproject.toml` on uv 0.13.2,
  but the checked-in file says `revision = 3`. `uv sync --locked` still accepts
  it, so `--locked` refuses *content* drift, not a stale revision number.
- `make spelling` regenerates the tracked `typos.toml` from the upstream
  shared dictionary on every run, so a plain `make markdownlint` leaves a
  modified tracked file in the working tree. The gate still exits 0; the
  rewrite reflects upstream dictionary drift, not this change. The plan
  reverts it rather than smuggling an unrelated regeneration into a Ruff
  commit, and the final commit leaves `typos.toml` untouched.

## Decision log

- Decision: keep `preview = true` and add `explicit-preview-rules = true`,
  rather than pinning an explicit code list with preview off. Rationale: issue
  #140 requires explicit preview adoption while retaining already adopted
  rules. Turning preview off would silently drop the 118 preview rules the
  project relies on today.
- Decision: derive the reviewed preview set from measurement, not from the
  prefix list. Rationale: `lint.rules.enabled` from `--show-settings` is the
  only place that reflects the binary, the config, and the selector logic in a
  way that can be diffed.
- Decision: record the inventory as generated data plus a contract test that
  *compares* rather than snapshots blindly. Rationale: the test must fail on an
  unreviewed addition **and** on an accidental removal; a snapshot alone
  reports only one direction.
- Decision: write the `D421` fix as a docstring-only edit to the summary line.
  Rationale: the rule targets the property summary; the explanatory paragraph
  and the implementation carry behaviour and should not churn.
- Decision: migrate `noqa` to `ruff: ignore[...]` for the codes Ruff owns, and
  keep the rationale after a second `#`. Rationale: RUF105 is explicitly
  described upstream as opinionated; a written decision plus a local contract
  is the difference between a policy and an unexplained suppression.
- Decision: enforce the suppression convention with a tokenizer-based contract
  over tracked Python files rather than a regex grep. Rationale: comments
  inside string literals would otherwise be counted, and the contract needs to
  distinguish inline, file-level, and block forms.
- Decision: hold the grouped update's other seven packages until the Ruff
  migration is green, then let Dependabot recreate the branch. Rationale: a
  passing Ruff migration does not certify the other packages; the separation
  keeps a failure attributable.

## Outcomes & retrospective

Not yet delivered. This section is completed at the end of milestone 4.

## Conformance basis

- Issue #140, "Make Ruff preview-rule adoption explicit and migrate the lint
  blockers exposed by Dependabot #129", acceptance criteria 1 to 5.
- Dependabot #129 (closed), head `7366a95844766d37df14b5a74fa0d204692f80de`.
- Dependabot #176 (open), head `b8bb4bdc8a89ac6d8033eb1875b3825f718aadef`,
  failing job `42041912849`.
- `docs/adr-002-four-tier-python-linting.md` defines the lint tiers this
  change must not collapse.
- `docs/developers-guide.md` "Python gates", "Linting", and "Spelling and new
  documents" sections document the gate behaviour this plan updates.
- `leynos/shared-actions#588` is the destination for the migration canary
  evidence; this plan deliberately does not create a runner.

Trace: `#140 AC1 -> M3 -> tests/test_d421... + migrated docstrings`;
`#140 AC2 -> M1 -> tests/ruff_policy_contract/`;
`#140 AC3 -> M3 -> tests/ suppression_contract/`;
`#140 AC4 -> M4 -> gate transcripts`;
`#140 AC5 -> M4 -> issue comment on shared-actions#588`.

## Verification plan

Obligations introduced or preserved by this change:

1. *Preview policy is a reviewed artifact.* Invariant: for every tracked
   Python file, the effective enabled-rule set equals the committed inventory.
   Method: contract test that runs the locked binary with `--show-settings`,
   extracts `linter.rules.enabled`, and compares. Non-vacuity: the test is
   shown to fail against a hand-edited inventory row and against a planted
   `pyproject.toml` selector change before it is accepted.
2. *A new preview rule cannot be picked up unreviewed.* Invariant: with
   `explicit-preview-rules = true`, selecting a prefix whose new preview member
   is not named produces no diagnostic for that member. Method: fixture that
   selects `D` and asserts an unselected preview verb-docstring is silent, then
   names it and asserts it flags. Non-vacuity: both halves run in the same
   test, so a detector that always or never flags fails one side.
3. *Suppression syntax keeps its security scope.* Invariant: an
   `ruff: ignore[S404]` suppresses S404 on its own line only; removing it
   restores S404; a same-line `F401` stays visible; a call-line `S603`
   suppression leaves an argument-line `S607` visible. Method: pytest fixtures
   in `tmp_path` run through the locked Ruff with
   `--isolated --preview --select … --output-format json`. Non-vacuity: the
   test asserts the diagnostic is *present* in the unsuppressed variant and
   *absent* in the suppressed one, so a fixture that never triggers cannot pass.
4. *Rationale and code scope are enforced locally.* Invariant: every suppression
   comment in `hecate/`, `tests/`, and `scripts/` has explicit codes and a
   non-empty rationale, has no bare `noqa`, and has no security code in
   file-level or block form. Method: tokenizer-based contract with positive and
   negative fixtures covering missing rationale, whitespace-only rationale, bare
   `noqa`, and `S603` inside `file-ignore`/`disable`. Non-vacuity: the
   negative fixtures are fed to the same checker function the repository scan
   uses.
5. *The gate runs the locked Ruff.* Invariant: the Ruff version the gate runs
   equals the version recorded in `uv.lock`, and `make build` syncs with
   `--locked`. Method: `tomllib` comparison against
   `sys.executable -m ruff --version`, plus a Makefile-reader assertion.
   Non-vacuity: the test asserts a version string that would change if the lock
   were regenerated.
6. *No behaviour change in `hecate`.* Invariant: `ArchitectureCheckResult.ok`
   keeps its truth table. Method: the existing unit and behavioural tests
   (`tests/test_output*.py`, `tests/test_warnings_cli.py`) must pass
   unmodified; no source line other than the docstring summary changes.

Axioms (treated as interface facts, not re-proved): Ruff's `--show-settings`
output format; Ruff's `ruff: ignore[...]` semantics as documented upstream;
`uv sync --locked` refusing lockfile content drift while accepting the
checked-in revision number; tokenizer behaviour for `#` comments in Python 3.14.

Residual gaps: the inventory records the *enabled set*, not per-file
suppression. Per-file policy is covered by requirement 4. Ruff's own behaviour
is not re-verified beyond the fixtures named above.

## Milestones

### Milestone 1: explicit preview adoption and a committed rule inventory

End state: `pyproject.toml` names every preview code this project has reviewed
under `[tool.ruff.lint]`, with `explicit-preview-rules = true`. A committed
inventory file holds the effective enabled-rule list for the pinned Ruff, and a
contract test fails when it differs. Recovery path: revert the two files and
the test; the repository is then exactly the baseline. Acceptance: the contract
test passes on the reviewed inventory and fails on a one-code edit.

### Milestone 2: reproducible Ruff provenance

End state: `make build` uses `uv sync --locked --group dev`, and a toolchain
contract asserts the lockfile version, the `--locked` spelling, and the running
binary agree. Acceptance: `make build` exits 0 without re-resolving, and the
test fails if `--locked` is removed or the lock is regenerated without updating
the expectation.

### Milestone 3: resolve the demonstrated blockers

End state: `ArchitectureCheckResult.ok`'s summary line describes the attribute;
every project-configured `noqa` for a Ruff-owned code is a code-scoped
`ruff: ignore[...]` with its rationale preserved; a tokenizer contract and Ruff
behaviour fixtures enforce both. Acceptance: the focused Ruff run over
`hecate tests scripts` is clean on the pinned version, and the fixtures
demonstrate suppression scope, restored diagnostics, and adjacent-diagnostic
visibility.

### Milestone 4: adopt the refreshed update and record the evidence

End state: the grouped Dependabot update is refreshed on the repaired baseline,
the newly added preview codes are reviewed and named, every repository gate
runs, and residual failures are diagnosed separately. Acceptance: transcripts
of each gate, each non-Ruff failure attributed to a named package, and a
comment posted to `leynos/shared-actions#588` carrying the minimal old/new
fixture and rule-set delta.

## Revision note

Revision 1: initial plan, written after reconnaissance. Records the measured
rule-set deltas for 0.15.13, 0.16.9, and 0.17.3, the discovery that
`explicit-preview-rules` is supported by the pinned binary while the new rule
codes are not, and the CI evidence that the live grouped update fails on the
same class of blocker plus `UP052`.
