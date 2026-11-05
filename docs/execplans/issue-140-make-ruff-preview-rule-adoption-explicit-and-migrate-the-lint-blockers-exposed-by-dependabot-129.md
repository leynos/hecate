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
2. A committed inventory plus a contract test compares the rule set Ruff
   reports as enabled for representative files with the committed data, so
   dropping a rule matters as much as adding one.
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
- [x] Write this plan and commit it (`74af1a6`).
- [x] Milestone 1: make preview adoption explicit on the pinned Ruff and pin
     the enabled rule inventory. `pyproject.toml` now sets
     `explicit-preview-rules = true` and names 106 preview codes under
     `extend-select`; the resolved set is byte-identical to the 673-code
     baseline; `tests/ruff_policy_contract/` holds the inventory, its readers,
     a two-directional comparison, and a behaviour fixture; the developers'
     guide documents the policy.
- [x] Milestone 1, review pass: `coderabbit review --agent` raised two
     findings. The per-file-ignore wording claimed per-file ignores changed the
     inventory set; they do not, and the four files that said so are corrected.
     The inert half of the behaviour fixture relied on `PLW1514` under an
     unselected prefix, which is silent for a second reason and would keep
     passing if the switch stopped working; the fixture now compares three
     variants of the repository's own configuration.
- [x] Milestone 1, second review pass: two more findings. `settings_dump` now
     documents its parameters and return value. The inventory test asserted a
     per-file property from one sample; the repository currently has only the
     root configuration, but nothing stopped a nested one from silently
     re-rooting resolution. A companion test now lists the tracked Python files
     through Git and fails if any directory below the root declares its own
     Ruff configuration.
- [x] Milestone 1, second review pass follow-up: the added readers took
     `tests/ruff_policy_contract/reading.py` to 452 lines against Pylint's
     400-line `max-module-lines`, failing `make lint`. The readers that decide
     *which* configuration applies to a file were split into
     `tests/ruff_policy_contract/discovery.py`; they answer a question about
     the gate's reach, while `reading.py` answers one about the rule
     selection, so the split follows the concern rather than a line budget.
     `REPO_ROOT` became public to share it.
- [x] Milestone 1, third review pass: three findings, all taken. The
     nested-configuration test walked only each file's own directory, so a
     `ruff.toml` in an intermediate directory holding no module directly
     escaped it; `directories_between` now walks every ancestor and a planted
     intermediate config proves it fires. The other two asked for complete
     NumPy sections on the public readers; those sections are now present
     throughout. Restoring them pushed `reading.py` back over the cap, so it
     was split again along the same concern: `inventory.py` reads the
     committed artefact and the dump it is regenerated from, `provenance.py`
     reads the lockfile and Makefile that pin the binary, and `reading.py`
     reads the configuration and the binary's resolved settings. The modules
     now run 109 to 311 lines each.
- [x] Milestone 1, fourth review pass: two findings. The nested-configuration
     scan listed only `*.py`, but Ruff checks `.pyi` stubs too, so a
     stub-only directory could hold a config the scan never saw; the pathspec
     now names both. The residual-gaps paragraph claimed requirement 4 covers
     per-file policy, when requirement 4 is about comments written in source
     files and `lint.per-file-ignores` was already documented as outside the
     inventory; the paragraph now says so.
- [x] Milestone 2: pin Ruff provenance in `make build` and add the toolchain
     contract. `build` now runs `uv sync --locked --group dev`, and
     `tests/ruff_policy_contract/test_provenance.py` asserts both that the
     recipe carries `--locked` and that the version `uv.lock` pins equals the
     version the virtualenv imports. Written red first: without the flag the
     build-recipe case failed on
     `['$(UV_ENV)', '$(UV)', 'sync', '--group', 'dev']`. A throwaway project
     with a deliberately drifted lock exits 1 under `--locked` and installs
     the new package without it, and `make build` here leaves `uv.lock`
     byte-identical. The developers' guide explains why the flag is there.
- [x] Milestone 3, part one: `D421` fixed by docstring-only edits. Six
     summary lines in `hecate/` and `scripts/nose_schema.py` began with
     `Return`/`Returns`, and eleven properties in
     `scripts/tests/test_duplication_gate_contention.py` followed the same
     shape. Each now opens with the noun phrase the attribute names, so no
     behaviour, signature, or code changed. Verified clean on both 0.16.9 and
     0.17.3 across `hecate tests scripts`.
- [x] Milestone 3, part two: all 30 `noqa` comments migrated to
     `ruff: ignore[CODE]  # reason`, and two new contracts added.
     `tests/ruff_policy_contract/suppressions.py` reads comments by tokenizing
     rather than by regex over the file, so a `#` inside a string literal is
     never policy. `test_suppressions.py` applies the house convention to every
     module Ruff reports for `hecate tests scripts`;
     `test_reading_suppressions.py` applies the same two functions to literal
     text, which is what makes the
     repository scan non-vacuous; `test_suppression_behaviour.py` runs the
     pinned binary over fixtures in `tmp_path` to prove the migrated spelling
     actually suppresses, and only where Ruff reports the code. Three seeded
     mutations of the reader and of the broad-form rule each failed the suite
     (21, 6, and 3 failures respectively), and the restored tree is 70 passed.
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
- A nearer configuration silently re-roots the resolution. A probe with a
  `sub/pyproject.toml` carrying `[tool.ruff.lint]` made `--show-settings` for a
  file in `sub/` report only the `F` rules, ignoring the root policy entirely,
  and a `pyproject.toml` *without* `[tool.ruff]` was ignored as expected. That
  is why the single-row inventory needs the companion "no nested configuration"
  test rather than a second sample.
- `linter.rules.enabled` in `--show-settings` is identical for every Python
  file in the repository. `per-file-ignores` is reported as its own
  `linter.per_file_ignores` structure and does not enter that set: it is a
  separate setting Ruff consults when it checks each file. One inventory row is
  therefore sufficient for the selected set, and a code listed there may still
  be ignored on a particular path. Per-file behaviour belongs in a separate
  assertion; it is out of scope for this inventory.
- The repository caps a module at 400 lines (`max-module-lines` in
  `pyproject.toml`). Reading Ruff's policy presses on that cap from two
  directions at once: the configuration needs many small readers because each
  one raises rather than returning a default, and `--show-settings` is a human
  dump that needs its own tolerant-but-strict parser. The cap is a real design
  input here, not incidental. Grouping the readers by the question they answer
  keeps each module under it without merging concerns.
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
  rewrite reflects upstream dictionary drift, not this change. The plan reverts
  it rather than smuggling an unrelated regeneration into a Ruff commit, and
  the final commit leaves `typos.toml` untouched.
- Twelve preview codes were already named individually in `select` before this
  change (`PLE4703`, `PLR0202`, `PLR0203`, `PLR0914`, `PLR0916`, `PLR1702`,
  `PLR6104`, `PLR6201`, `PLR6301`, `RUF036`, `RUF055`, `RUF066`), so the
  reviewed preview set is 118 codes, not the 106 that moved to `extend-select`.
  `PLW0108`, `RUF053`, and `RUF064` sit in the same block but are stable on
  0.15.13 and stay in `select` untouched.
- The behaviour fixture cannot use `D421` or `RUF105` to demonstrate explicit
  adoption: neither exists on the pinned 0.15.13 binary (`ruff rule D421`
  answers `invalid value 'D421'`). The fixture uses `D420`
  (incorrect-section-order) as the adopted preview rule, which works on the
  pinned version and keeps the demonstration honest.
- A first attempt showed inertness with `PLW1514`, a preview rule under the
  `PLW` prefix the project does not select. That case is silent for two
  independent reasons, so it cannot distinguish "explicit adoption works" from
  "the rule was never in scope", and it would keep passing if
  `explicit-preview-rules` stopped working. The fixture now compares three
  versions of the repository's *own* copied configuration that differ in one
  line: `D420` adopted (fires), adoption line removed with the `D` prefix still
  selected (inert), and adoption removed *and* `explicit-preview-rules` off
  (fires again). The third is the control that makes the second meaningful.
  Running the suite with `explicit-preview-rules = false` in the working
  `pyproject.toml` fails the inert case, which is the non-vacuity evidence for
  this fixture.
- The repository's numpy docstring convention is what makes `D420` fire, so
  the fixture's first attempt passed a Google-style docstring and produced only
  `D100`/`D406`/`D407` — it looked like the rule was off. A copied
  configuration needs a violation that matches the configured convention, not
  just a violation in the abstract.
- Where Ruff reports a diagnostic decides where the suppression has to go, and
  the two security codes differ. S603 is reported on the `subprocess.run(` call
  line; S607 is reported on the line holding the argument vector. For a
  single-line call those are the same physical line and a trailing comment
  covers both. For a multi-line call they are different lines, and placement
  and code list are separate questions. An own-line comment above the call
  covers the *entire logical line*, so one comment naming both codes covers
  both, while a comment naming only S603 leaves S607 visible because the code
  does not match. A trailing comment, or an own-line comment inside the call,
  covers one physical line only, so S607 then needs a comment on or directly
  above the vector's line. Measured on the pinned binary: an own-line
  `# ruff: ignore[S603, S607]` above a multi-line `subprocess.run(` clears both,
  `[S603]` alone leaves S607, and `[S607]` inside the call leaves S603.
  `discovery.py` uses the last form: its own-line `# ruff: ignore[S607]` sits
  above the vector inside a `subprocess.run(` whose call line is separate.
- A suppression on the call line of a multi-line call does not reach the
  argument line, and a suppression on the argument line does not reach the call
  line. That asymmetry is what makes "put it where Ruff reports it" both
  necessary and sufficient, and it is now pinned by
  `test_a_call_line_suppression_does_not_reach_an_argument_line`.
- Ruff 0.17 finds a suppression directive *anywhere* in a comment that a `#`
  introduces, including inside prose and inside backticks, not only at the
  comment's start. A comment documenting the syntax, such as one naming a code
  inside double backticks, is therefore a live directive: 0.17.3 reports it as
  an unused suppression, or warns that it is invalid. 0.16.9 does not, so this
  class of mistake is invisible on the pinned 0.15.13 binary and appears on
  upgrade. The reader now searches rather than anchors to match, and the
  repository contract immediately flagged the two explanatory comments in
  `suppressions.py` itself, which is the strongest evidence that the rule has
  teeth. Documentation of this syntax must be written without a literal
  directive.
- Ruff accepts `ruff:ignore` without a space after the colon, and accepts a
  directive with no brackets, but only the bracketed form is a directive:
  `# ruff: ignore` with no code list is silently inert, and neither RUF100 nor
  RUF104 remarks on it.
- `ty` rejected the readers' `dict[str, object]` parameters: `dict` is
  invariant in its value type, so the literal nested tables the negative cases
  pass in do not conform. The readers now take `collections.abc.Mapping` and
  narrow at one helper, which is also the honest type for "read-only parsed
  TOML".

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
- Decision: enable `--preview` in the behaviour fixtures, and add a case
  asserting that the migrated syntax is inert without it. Rationale: measured,
  not assumed — with preview off, Ruff emits
  `#ruff:ignore comment found but not active, enable preview mode` and still
  reports the diagnostic. Every scope assertion in the fixture file would
  otherwise have passed while proving nothing about the mode the project
  actually runs.
- Decision: give each fixture the smallest argument vector that trips the code
  under test, rather than one vector that trips both. Rationale: measured —
  S603 fires only when the vector is not entirely literal strings, while an
  all-literal `['make']` draws S607 alone. One variable element
  (`name = 'make'`, then `['make', name]`) produces both, which is why the
  suppression scope fixture uses that shape and the single-code cases do not.
- Decision: record a bracket-less `ruff: ignore` as a suppression, even though
  Ruff treats it as prose. Rationale: measured — a call line carrying that
  comment as a trailing suppression still reports S607, and RUF100 does not
  flag the comment as unused, so Ruff does not warn. A comment an author
  believes suppresses something and which in fact suppresses nothing is exactly
  what the contract should catch, and only the reader can catch it.
- Decision: keep the readers and the convention in separate modules
  (`suppressions.py` reads; `test_suppressions.py` judges), so the literal-text
  fixtures import the same function the repository scan uses. Rationale: the
  plan's requirement 4 asks for fixtures fed to that checker; a second judging
  implementation in the test file would prove only that the copy works.
- Decision: enforce the suppression convention with a tokenizer-based contract
  over tracked Python files rather than a regex grep. Rationale: comments
  inside string literals would otherwise be counted, and the contract needs to
  distinguish inline, file-level, and block forms.
- Decision: put `--locked` in the `build` goal rather than in a separate
  target or in `UV_ENV`. Rationale: `build` is what CI runs and what every
  other gate depends on, so the flag reaches every install path without a new
  invocation to remember. A separate target would leave the re-resolving one
  available and reachable.
- Decision: assert the lock and the running interpreter agree, and assert the
  recipe carries `--locked`, as two separate cases. Rationale: each can be true
  while the other is false. A `--locked` build of a lock that no longer matches
  `pyproject.toml` fails loudly, but one that matches yet pins a different Ruff
  than the virtualenv imports would still pass a recipe-only check.
- Decision: write the spaced form, and do not migrate it to the compact
  spelling. Rationale: a review claimed the pinned 0.15.13 cannot read the
  spaced form, that the spacing arrived in 0.16.0, and that the compact
  spelling is the one each version understands. Measured on 0.15.13 with
  `--isolated --preview --select=S607`, all four combinations behave
  identically: the spaced form with a matching code passes, with a non-matching
  code reports the diagnostic, and the compact form does the same in both
  cases. Without `--preview` both forms are inert and print the same
  `#ruff:ignore comment found but not active` warning. So the compact spelling
  is equivalent, not required, and the gate that produced the green result
  already ran the spaced form over `scripts/`. Switching would churn 30
  comments for no behavioural gain and would diverge from the documentation and
  from Ruff's own examples.
- Decision: keep rule codes in the suppression comments, and do **not** add
  `RUF106` to `extend-ignore`. Rationale: `RUF106`
  (`rule-codes-in-suppression-comments`) is a preview rule that asks for
  human-readable rule names. It is not selected, and not reported. Measured on
  0.17.3 with the repository's own configuration, over `hecate tests scripts`:
  `All checks passed!` with exit 0. `--select=RUF106` alongside the project
  config reports 37 findings, so the rule does fire when named and the green
  result is the `explicit-preview-rules = true` setting doing its job — a bare
  `RUF` prefix acquires stable rules only. `--isolated` agrees:
  `--select=RUF --preview` reports `F401` and no `RUF106`, while
  `--select=RUF106 --preview` reports it. Two consequences follow. The 37
  findings are latent rather than absent, and they become live the day `RUF106`
  is named in `extend-select` or `explicit-preview-rules` is dropped, so this
  decision must be revisited with the rule, not discovered by a future
  dependency bump. And the codes are what the contract reads:
  `tests/ruff_policy_contract/test_suppressions.py` matches upper-cased codes,
  and rule names are themselves preview-only in selectors and suppression
  comments, so a name-based spelling would make the gate depend on preview
  semantics twice over. Ignoring `RUF106` explicitly was rejected:
  `extend-ignore` is not a prefix, so the entry would be inert until the rule
  is selected, and a dormant entry that reads as a decision is worse than a
  recorded one that is not yet needed.
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

Trace: `#140 AC1 -> M3 -> the D421-clean run over hecate tests scripts`;
`#140 AC2 -> M1 -> tests/ruff_policy_contract/test_preview_adoption.py`;
`#140 AC3 -> M3 -> tests/ruff_policy_contract/test_suppressions.py`,
`test_reading_suppressions.py`, `test_suppression_behaviour.py`;
`#140 AC4 -> M4 -> gate transcripts`;
`#140 AC5 -> M4 -> issue comment on shared-actions#588`.

## Verification plan

Obligations introduced or preserved by this change:

1. *Preview policy is a reviewed artifact.* Invariant: for every tracked
   Python file, the set Ruff reports as enabled equals the committed inventory,
   and per-file ignores do not enter that set. A single inventory row is only
   honest while one configuration governs the whole tree, so a companion
   invariant forbids a nearer configuration: no directory below the root may
   hold a `pyproject.toml` with `[tool.ruff]`, a `ruff.toml`, or a
   `.ruff.toml`. Method: contract tests that run the locked binary with
   `--show-settings`, extract `linter.rules.enabled`, and compare; the
   companion test lists the tracked Python files through Git and checks each
   directory's candidates. Non-vacuity: the inventory comparison is shown to
   fail against a hand-edited row and a planted selector change, and the
   companion test fails against a planted `hecate/pyproject.toml` and against a
   planted `tests/ruff.toml`.
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

Residual gaps: the inventory records the selected set Ruff reports, not
per-file suppression. Requirement 4 covers suppression comments written in
source files only; `lint.per-file-ignores` and `lint.extend-per-file-ignores`
are configuration, not comments, and stay outside the contract, as the package
docstring and `test_inventory.py` both state. Ruff's own behaviour is not
re-verified beyond the fixtures named above.

## Milestones

### Milestone 1: explicit preview adoption and a committed rule inventory

End state: `pyproject.toml` names every preview code this project has reviewed
under `[tool.ruff.lint]`, with `explicit-preview-rules = true`. A committed
inventory file holds the enabled-rule list Ruff reports for the pinned binary,
and a contract test fails when it differs. Recovery path: revert the two files
and the test; the repository is then exactly the baseline. Acceptance: the
contract test passes on the reviewed inventory and fails on a one-code edit.

Delivered. `explicit-preview-rules = true` sits in `[tool.ruff.lint]` above
`select`, with a comment that says why; `extend-select` names 106 preview codes
grouped by linter. The resolved set is byte-identical to the pre-change 673,
measured by diffing `linter.rules.enabled` from `--show-settings` before and
after. `tests/ruff_policy_contract/` holds `reading.py` (the configuration and
the binary's resolved settings), `inventory.py` (the committed artefact and the
dump it is regenerated from), `provenance.py` (the lockfile and Makefile that
pin the binary), `discovery.py` (which configuration governs which file),
`enabled_rules.txt` (the reviewed inventory with a `# ruff-version: 0.15.13`
header), `test_reading.py` (reader negative cases), `test_inventory.py` (the
two-directional comparison, the policy switches, and the single-row
precondition), and `test_preview_adoption.py` (the behaviour fixture).
Acceptance evidence:

```plaintext
$ uv run pytest tests/ruff_policy_contract -q
32 passed

# inventory with F401 deleted
AssertionError: Ruff now enables rules the inventory does not list ... ['F401']
# inventory with XYZ999 appended
AssertionError: Ruff no longer enables rules the inventory lists ... ['XYZ999']
```

`docs/developers-guide.md` gained a "Ruff preview policy" section covering the
switch, where to add an adoption, the regeneration command, and the fact that
the inventory is reviewed data rather than a snapshot. `make check-fmt`,
`make lint`, `make typecheck`, `make test`, `make markdownlint`, and
`make nixie` all pass.

### Milestone 2: reproducible Ruff provenance

End state: `make build` uses `uv sync --locked --group dev`, and a toolchain
contract asserts the lockfile version, the `--locked` spelling, and the running
binary agree. Acceptance: `make build` exits 0 without re-resolving, and the
test fails if `--locked` is removed or the lock is regenerated without updating
the expectation.

Delivered. The build recipe carries `--locked`, and
`tests/ruff_policy_contract/test_provenance.py` holds two cases over the real
files plus two over the readers. The first case compares `locked_ruff_version`
with `installed_ruff_version`; the second requires `--locked` in the joined
recipe. Acceptance evidence, from a throwaway project whose `pyproject.toml`
gained a dependency after `uv lock`:

```plaintext
$ uv sync --locked
error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.
hint: To update the lockfile, run `uv lock`.
exit=1

$ uv sync
Resolved 2 packages
Installed 1 package
  + six==1.17.0
exit=0
```

In this worktree, `make build` printed `Resolved 45 packages` from the lock and
left `uv.lock` byte-identical (`sha256sum -c` reports `uv.lock: OK`). The
recovery path is to revert the one Makefile line and the test file, which
returns the repository to the baseline.

### Milestone 3: resolve the demonstrated blockers

End state: `ArchitectureCheckResult.ok`'s summary line describes the attribute;
every project-configured `noqa` for a Ruff-owned code is a code-scoped
`ruff: ignore[...]` with its rationale preserved; a tokenizer contract and Ruff
behaviour fixtures enforce both. Acceptance: the focused Ruff run over
`hecate tests scripts` is clean on the pinned version, and the fixtures
demonstrate suppression scope, restored diagnostics, and adjacent-diagnostic
visibility.

Delivered. The `D421` edits are docstring-only and touch no signature or
statement. The migration rewrote 30 `noqa` comments across 12 files; the only
ones left in the tree are two `S310` comments in `scripts/typos_rollout.py`,
which `extend-exclude` keeps out of the gate, so rewriting them would be policy
no gate enforces.

Three modules carry the new contract. `suppressions.py` tokenizes and returns a
`Suppression` record with its line, form, codes, and rationale; it is
deliberately judgement-free. `test_suppressions.py` holds the judgement and the
repository scan, asking Ruff for `--show-files hecate tests scripts` so an
excluded module is not failed for a comment the gate never reads (95 files, and
`scripts/typos_rollout.py` is absent from that list).
`test_reading_suppressions.py` feeds literal text to those same two functions,
which is what makes a passing repository scan mean something.
`test_suppression_behaviour.py` proves the syntax rather than the reading.

Non-vacuity was demonstrated by seeding faults. Making `has_reason` always true
failed 6 cases; making the reader return nothing failed 21, including the
repository scan's own non-vacuity test; removing the broad-form rule from
`violations` failed the 3 broad-form cases. The restored tree is 70 passed, and
`uv run ruff check hecate tests scripts` reports `All checks passed!`.

The behaviour fixtures also changed two of the plan's assumptions. The plan
said to run them through Ruff with `--isolated --preview`; the `--preview` half
turned out to be load-bearing, not decoration, and now has its own case. And
the plan implied one fixture could trip both security codes; in fact an
all-literal vector trips S607 alone and only a vector with a variable element
trips S603. Both facts are recorded in `Surprises & discoveries` because a
future maintainer adding a fixture will otherwise repeat the mistake.

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
