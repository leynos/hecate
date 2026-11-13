# Make Ruff preview-rule adoption explicit and migrate the lint blockers exposed by Dependabot #129

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: COMPLETE.

Issue: <https://github.com/leynos/hecate/issues/140>

## Purpose / big picture

Hecate's Ruff configuration sets `preview = true` in `[tool.ruff]` and selects
whole prefixes such as `D`, `RUF`, `S`, `E`, `FURB`, and `PLR`. With preview
enabled, a prefix is not a fixed set of rules: it is "every rule in that
prefix, including the ones upstream is still prototyping". Ruff 0.15.13 was the
reviewed version and enabled 673 rules. Ruff 0.16.9 enables 682, adding `D421`
and eight others without any edit to `pyproject.toml`. Ruff 0.17.3 adds `UP052`
for a tenth. The dependency update is therefore not a neutral tooling bump: it
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
   keeps another tool's pragma on a shared line — the last to the extent it can
   be shown without a coverage run, which is that the pragma survives verbatim
   and the suppression beside it still works.

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
  `TestTwoToolsOneLine` in
  `tests/ruff_policy_contract/test_suppression_shared_line.py` runs the pinned
  binary over fixtures where a migrated directive shares one comment with
  `# pragma: no cover`, in both orders, and asserts the directive still silences
  `S404` while `F401` on the same line stays reported. A pragma with no
  directive is the negative control, and still draws `S404`. The coverage side
  is measured out of band and recorded in "What remains open": on a line that
  never executes, both directive orders and a pragma-only control report it as
  excluded by coverage 7.17.2, while the no-comment control reports it missing.
  It is not a suite assertion because adding `coverage` would edit the two
  files issue 176 also edits.
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
- [x] Milestone 3, part one: `D421` fixed by docstring-only edits. Sixteen
     summary lines began with `Return`/`Returns` and were rewritten to open
     with the noun phrase the attribute names: five in `hecate/checker.py`,
     `hecate/diagnostics.py` and `hecate/namespaces.py`, four in
     `scripts/nose_schema.py`, and seven properties in
     `scripts/tests/test_duplication_gate_contention.py`. No behaviour,
     signature, or code changed. Verified clean on both 0.16.9 and 0.17.3
     across `hecate tests scripts`.
- [x] Milestone 3, part two: all 28 `noqa` comments across 11 files migrated to
     `ruff: ignore[CODE]  # reason`, and two new contracts added.
     `tests/ruff_policy_contract/suppressions.py` reads comments by tokenizing
     rather than by regex over the file, so a `#` inside a string literal is
     never policy. `convention.py` holds the judgement as an ordered tuple of
     pure predicates;
     `test_suppressions.py` applies it to every module Ruff reports for
     `hecate tests scripts`; `test_reading_suppressions.py` applies the same
     reader and judgement to literal text, which is what makes the
     repository scan non-vacuous; `test_suppression_behaviour.py` runs the
     pinned binary over fixtures in `tmp_path` to prove the migrated spelling
     actually suppresses, and only where Ruff reports the code;
     `test_suppression_shared_line.py` proves the same spelling still
     suppresses when the comment shares its line with another diagnostic or
     with a coverage pragma. Three seeded
     mutations of the reader and of the broad-form rule each failed the suite
     (21, 6, and 3 failures respectively), and the restored tree is 70 passed.
- [x] Milestone 3, fifth review pass: two findings, both taken. A regex hole
     wider than the one reported: `# ruff: noqa: S607` and `# flake8: noqa` on
     their own line are *file-level* suppressions on 0.17.3, and the reader
     matched only a bare lower-case `noqa`, so both read as prose and the whole
     module they silenced was clear. The pattern now accepts either prefix and
     is case-insensitive, and five literal fixtures (prefixed with codes,
     prefixed bare, no space, upper-case, trailing) prove it. A drift test
     binds the scan's `LINT_TARGETS` to Ruff's own `--show-files` output. Both
     were shown to fail when their fix is reverted: 6 and 17 named modules.
- [x] Milestone 3, sixth and seventh review passes: two findings raised and
     falsified by measurement, one clarified. Ruff 0.15.13 reads the spaced
     `# ruff: ignore[...]` form exactly as it reads the compact spelling (all
     four suppression/non-suppression combinations identical, and both inert
     without `--preview`), so the 28 migrated comments were not rewritten. The
     RUF106 claim that `explicit-preview-rules` is absent was measured false:
     it is set at `pyproject.toml:52` and 0.17.3 reports `All checks passed!`.
     The suppression-placement bullet conflated line placement with the codes
     a comment names; it now separates them and carries the measurement.
- [x] Milestone 3, fourteenth review pass: three findings, all taken, and one
     of them widened by measurement. The code-shape bound accepted at most four
     prefix letters, but `ASYNC` is the longest prefix Ruff ships (measured over
     all 970 codes on 0.17.3: every code matches `^[A-Z]+\d+$`, prefixes one to
     five letters, three or four digits), so `ASYNC100` was reported as
     malformed; the bound is now `{1,5}`. `ruff: enable` no longer needs its own
     rationale — a `disable`/`enable` pair is one reviewed decision and the
     reason lives on the opening comment. The third finding asked for
     `re.IGNORECASE` to be dropped from the directive pattern; that would have
     made the reader *skip* wrongly-cased directives as prose, which is worse,
     and measurement showed the real problem is wider than reported: Ruff
     matches the prefix, the name **and the codes** case-sensitively, reports
     nothing at all for a wrong-case prefix or code, and would therefore leave a
     wrongly-cased comment clearing nothing while reading as policy. The pattern
     still matches case-insensitively so those comments are *read*, the record
     now keeps the literal spelling, `records_canonical_case` decides whether
     Ruff would honour it, and the contract reports the ones it would not.
     `noqa` is read in any casing but its code list is not. Two existing
     fixtures encoded the falsified assumption (a `RUFF: IGNORE[s603]`
     normalization test and an accepted lower-case `s603`) and were replaced.
     The casing fixtures moved to `test_reading_casing.py`, which is a
     separate question from placement, after the additions took
     `test_reading_suppressions.py` to 426 lines against Pylint's 400 cap.
- [x] Milestone 3, fifteenth review pass: one finding, taken. The
     partial-checkout guard checked only `pyproject.toml` and the sampled
     module, while `test_provenance.py` went on to read `uv.lock` and the
     `Makefile` through readers that raise rather than return nothing. The
     predicate's own docstring already said the mutation sandbox "need not
     carry the repository root or the lockfile", so it disagreed with itself. A
     partial checkout carrying the first two files and not the third therefore
     reported an `IOError` instead of skipping. `repository_files_present` now
     takes caller-specific paths, which `test_provenance.py` uses for the
     lockfile and `Makefile` and `test_inventory.py` for `enabled_rules.txt`.
     Written red first: the new `test_guard.py` failed with `TypeError:
     repository_files_present() takes 0 positional arguments`. Removing
     `uv.lock` now skips the four provenance cases and restores cleanly; the
     unguarded `lock_text()` raises `FileNotFoundError` on the same tree, which
     is the failure the guard prevents.
- [x] Milestone 3, sixteenth review pass: three findings, all taken. The
     selector check asked only that an `extend-select` entry be upper-case and
     end in a digit, which `PLR09` satisfies while naming nothing; the shape is
     now a shared predicate, `reading.is_rule_code`, full-matched against the
     measured `[A-Z]{1,5}\d{3,4}`. It has one definition and two contract
     modules import it, so the selector check and the suppression check cannot
     drift. The negative control is `test_reading_rule_codes.py`, which also
     separates a five-letter bound from a six-letter one (a lone `ASYNC100`
     witness accepts both, so it proves nothing about the bound). Two candidate
     fixtures were discarded during the pass — `PLR091` and `XPLR0911` follow
     the measured grammar and are merely not real rules, which no textual shape
     can decide; the inventory comparison is what rejects them. The
     Git-dependent walk in `test_inventory.py` now carries a test-level
     `skipif` on `.git` rather than relying on the module-wide guard, which
     does not cover the `git ls-files` call inside `checked_python_files`.
     The scope tolerance overrun is recorded in the decision log with measured
     counts and escalated; see that entry.
- [x] Milestone 4: adopt Ruff 0.17.3 and record the evidence. Locked with
     `uv lock --upgrade-package 'ruff==0.17.3'`; the lock still holds the same
     45 packages and only Ruff changes version, though uv also bumped the
     lock's own `revision = 3` to `5`. Under the **new** configuration the
     resolved rule set is identical: 673 codes before and after, none added,
     none removed, and 0.17.3 and 0.17.4 resolve identically. That is the
     setting doing its job: `explicit-preview-rules = true` keeps the three
     blockers (`D421`, `RUF105`, `UP052`) inert, so no source change was
     needed for them. The one behaviour that did move is the suppression
     syntax, recorded in `Surprises & discoveries`. `enabled_rules.txt`
     changes by its version header alone, and every gate passes: fmt,
     check-fmt, lint (Ruff 0.17.3, Pylint 10.00, Skylos, duplication),
     typecheck, 734 tests, markdownlint, nixie.
- [x] Milestone 4, acceptance scope: **Ruff-only validation complete;
     refreshed-group validation pending.** AC4 reads "the refreshed dependency
     update passes all existing required gates", and the refreshed grouped
     update is Dependabot #176, which is still open at
     `b8bb4bdc8a89ac6d8033eb1875b3825f718aadef` with `lint-test` failing
     (run `42041912849`). This branch validates Ruff 0.17.3 on the repaired
     baseline and every gate passes here; it does not, and cannot, validate a
     grouped update that has not been rebased onto this baseline. That is a
     pending dependency, not a defect in this change: #176 must be refreshed
     onto this branch's merge base before its own AC4-style claim can be made.
     The narrowing is recorded here so the acceptance mapping is not read as
     claiming more than was measured.
- [x] Milestone 4, review pass: three findings, all taken. Two were spelling
     (`artefact`, `stabilized`). The third was structural and correct:
     `reporting.py` is the non-test seam the fixtures import, and it was
     importing `test_suppressions` to reach `violations`, so it also evaluated
     that module's `pytestmark` and inherited a repository-presence skip
     condition for a scan it does not perform. The judgement moved to
     `convention.py`, which reads no files; `test_suppressions.py` keeps only
     the scan. `violations` itself is unchanged, so the suite stays at 132
     passed. The follow-up review returned 0 findings.
- [x] Measured the old-configuration delta, which the earlier record did not
     separate: on the base `pyproject.toml` (`preview = true` only), 0.15.13
     resolves 673 codes and 0.17.3 resolves **683**, adding ten preview rules
     (`D421`, `RUF074`, `RUF075`, `RUF077`, `RUF105`, `RUF106`, `RUF201`,
     `UP048`, `UP051`, `UP052`). Dependabot #176's 19-error failure is three of
     those ten. This is the four-cell matrix in `Outcomes & retrospective`.
- [x] Feed the old/new fixture and rule-set delta to
     `leynos/shared-actions#588`. Posted as
     <https://github.com/leynos/shared-actions/issues/588#issuecomment-6668251648>:
     versions, both configurations, the four-cell matrix, the reproduced
     19-error CI failure at head `b8bb4bd`, the suppression-behaviour pair,
     the suggested fixture shape, and an explicit statement of what is not
     claimed.
- [x] Push, open a draft pull request, and hand the migration evidence to
     `leynos/shared-actions#588`. Pushed over SSH; remote head `8fcfdf7`
     matches local `HEAD`, and the tracking ref was refreshed with a leading
     `+` refspec and the upstream set to `origin`. Draft PR:
     <https://github.com/leynos/hecate/pull/178>, titled with `(#140)`,
     stating `Closes #140`, with the Lody session under `## References`.
- [x] Cleared the two hosted CodeScene findings on the new contract modules by
     refactoring, not suppression. `reading.py` measured 9.38 for Code
     Duplication across the four `[tool.ruff.lint]` readers and `convention.py`
     9.69 for Complex Method on `violations` (cc 11). `reading.py` now
     delegates to two private readers and the four public names keep their
     signatures; `convention.py` holds the convention as an ordered tuple of
     one-message predicates. Both measure 10.00. Neither is a behaviour change:
     the suite stays at 132 passed, and a seeded fault in each (dropping one
     rule from the tuple; pointing `extend-select` at `select`) fails 5 and 2
     tests respectively, so the new shape is not vacuous.
- [x] Reapplied `mdtablefix --wrap` to this document and pushed as `7c15b42`;
     CI's `lint-test` went green on the new head.
- [x] Final CodeRabbit pass over the branch, on head `e8e45af`. It raised two
     findings, both in the contract suite and both verified against the code
     before acting. `inventory_codes` carried its own `[A-Z]+\d+` pattern
     beside `reading.is_rule_code`'s `[A-Z]{1,5}\d{3,4}`, so it accepted
     `PLR0`, `PLR09` and `PLR09111` that the selector and suppression
     contracts refuse; it now delegates. The existing negative cases (`"D"`,
     `"F 401"`) are refused by both shapes, so a new parametrized test covers
     the three entries only the strict one refuses, and restoring the loose
     pattern fails all three. Separately, the fixture labelled "six-digits"
     held `PLR09111`, which has five and duplicated the case above it; it now
     uses `PLR091112`. Committed as `e43841b`, all seven gates green
     (728 passed), and pushed with the tracking ref refreshed.
- [x] Refreshed the generated `typos.toml` against the shared oxendict base and
     committed it as `9284bb0`; the refresh is deterministic, so the diff is
     reviewable. With it the branch stands at head `9284bb0`, tree clean and
     local `HEAD` equal to the remote branch.
- [x] Corrected two stale figures in this document before the hosted
     assessments were requested. The retrospective's commit count still said
     32 and its cost paragraph still said 40 files / 4143 insertions / 77
     deletions; measured against `74af1a6~1` at `9284bb0` the branch carries
     40 commits and 41 non-ExecPlan files changed with 4217 insertions and 78
     deletions. Both drifted across the three commits pushed after the section
     was written, which is the ordinary cost of a living document whose
     numbers are measurements rather than restatements.
- [x] Answered the completeness assessment's two substantive findings. The
     missing `TestTwoToolsOneLine` fixtures now exist in
     `tests/ruff_policy_contract/test_suppression_shared_line.py`, with six
     cases covering the unsuppressed import, the co-located `F401`, the
     neighbouring import, a pragma-only negative control, and a shared comment
     in both orders. The runner they share moved to
     `tests/ruff_policy_contract/ruff_run.py`, a non-test seam, because
     putting the fixtures in the existing module took it to 431 lines against
     Pylint's 400-line cap, and importing one test module from another would
     inherit its `pytestmark` — the same defect this plan already fixed for
     `reporting.py`. AC4 is now recorded as Ruff-only validation with the
     refreshed grouped update pending at #176. All seven gates pass:
     fmt, check-fmt, lint (Ruff clean, Pylint 10.00/10, Skylos clean,
     duplication 5 reasoned exceptions), typecheck, **734 tests**,
     markdownlint, nixie.

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
  shared dictionary on every run. Before the refresh was committed, a plain
  `make markdownlint` therefore left a modified tracked file in the working
  tree; that dirty-worktree observation dates from before `9284bb0` and no
  longer describes the tree. Two things that note ran together belong apart:
  the gate **exited 0** while the file was modified, which is the gate passing
  despite the rewrite, and the worktree was dirty, which is a separate fact
  about the tree rather than about the gate's verdict. The plan's first
  response was to revert the rewrite rather than smuggle an unrelated
  regeneration into a Ruff commit. That was not the final state: the refresh
  proved deterministic and reviewable, so it is committed separately as
  `9284bb0` and the file therefore *is* changed by this branch. Keeping the
  regeneration out of the Ruff commits and giving it its own is what the
  original note was protecting; leaving `typos.toml` untouched entirely was not
  achievable while also passing the Markdown gate.
- Twelve preview codes were already named individually in `select` before this
  change (`PLE4703`, `PLR0202`, `PLR0203`, `PLR0914`, `PLR0916`, `PLR1702`,
  `PLR6104`, `PLR6201`, `PLR6301`, `RUF036`, `RUF055`, `RUF066`), so the
  reviewed preview set is 118 codes, not the 106 that moved to `extend-select`.
  `PLW0108`, `RUF053`, and `RUF064` sit in the same block but are stable on
  0.15.13 and stay in `select` untouched.
- The behaviour fixture cannot use `D421` or `RUF105` to demonstrate explicit
  adoption: neither exists on the then-pinned 0.15.13 binary (`ruff rule D421`
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
  class of mistake is invisible on the then-pinned 0.15.13 binary and appears
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
- Ruff's suppression spelling is case-sensitive at every position, in both
  spellings — a fact that measurement alone established. Over a call tripping
  S607 on the then-pinned 0.15.13: the canonical `ruff: ignore[S607]`
  suppresses it; `RUFF: ignore[S607]`, `Ruff: Ignore[S607]`,
  `ruff: IGNORE[S607]` and `ruff: ignore[s607]` all leave it reported; and
  `# noqa: s607` leaves it reported too, while `# NOQA: S607` suppresses it.
  Ruff reports only the wrongly-cased directive *name* (`RUF103`, "unknown ruff
  directive"), and draws no diagnostic at all for a wrong-case prefix or a
  wrong-case code. This is the single most dangerous failure mode the reader
  has to cover: the comment looks reviewed, changes nothing, and the linter
  stays silent. The contract is therefore the only guard, and it reads every
  casing deliberately.
- The 970 rule codes Ruff 0.17.3 ships all match `^[A-Z]+\d+$`, with prefixes
  one to five letters (`ASYNC` is the longest) and three or four digits. That
  measured shape is what the contract's code-shape rule is built on; it
  supplanted a guessed four-letter bound that rejected `ASYNC100`.
- Ruff stabilized `ruff: ignore` between 0.15.13 and 0.17.4, and it did so
  without a rule-set delta. On 0.15.13 the syntax was preview-only: without
  `--preview` a `ruff: ignore[S603]` comment on a call that trips S603 still
  reported S603 and Ruff printed
  `#ruff:ignore comment found but not active, enable preview mode`. On 0.17.3
  and 0.17.4 the same comment suppresses S603 with `--isolated` and no
  `--preview`, and the warning is gone. The behaviour fixture that recorded the
  old premise (`test_the_syntax_is_inert_without_ preview`) therefore failed on
  the upgrade, which is exactly what a negative control should do; it now
  asserts the inverted fact and is renamed
  `test_the_syntax_suppresses_without_preview`. What did **not** stabilize is
  rule *names* in the brackets: outside preview mode
  `ruff: ignore[subprocess-without-shell-equals-true]` still reports S603,
  while inside preview mode it suppresses it. That asymmetry is the measured
  reason the contract forbids names: a name-based suppression silently covers
  nothing in any stable-mode run, and the repository would not notice. The
  upgrade also showed why a rule-set inventory cannot be the only contract:
  this behaviour change would have been invisible to it, and only a fixture
  running the real binary caught it.
- The grouped update proposes Ruff 0.17.3, but `uv lock --upgrade-package ruff`
  resolves the newest 0.17.4. Both were measured against this configuration and
  resolve the same 673 codes, so the choice is not behavioural; 0.17.3 was
  pinned because it is the version the pull request under review proposes, and
  a branch newer than its own dependency update surprises reviewers for no gain.

## Decision log

- Decision: let the inventory reader delegate to `reading.is_rule_code` rather
  than carry its own pattern. Rationale: the issue's premise is that one
  reviewed definition should govern the tree, and a second pattern is the drift
  the contract exists to prevent. The cost is that the inventory parser now
  refuses shapes it previously accepted; every one of the 673 committed codes
  satisfies the strict shape, so nothing recorded has to change. The delegation
  is pinned by a test using entries only the strict shape refuses, because the
  pre-existing negative cases pass under both.
- Decision: adopt Ruff 0.17.3 alone and leave the grouped update's other seven
  packages to Dependabot. Rationale: recorded earlier and now executed. The
  upgrade changes no resolved rule and needs no source change, so the other
  packages would add failure surface without testing anything about the Ruff
  policy. When this branch merges, Dependabot's rebase drops Ruff from its own
  group and the remaining seven arrive as a reviewable diff.
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
  recording what happens to the migrated syntax without it. Rationale:
  measured, not assumed — on the then-pinned 0.15.13, with preview off, Ruff
  emitted `#ruff:ignore comment found but not active, enable preview mode` and
  still reported the diagnostic, so the case asserted inertness. Every scope
  assertion in the fixture file would otherwise have passed while proving
  nothing about the mode the project actually runs. **This decision was
  overtaken during the 0.17.3 upgrade:** the syntax stabilized, the case was
  renamed `test_the_syntax_suppresses_without_preview`, and it now asserts the
  opposite — that the comment suppresses with no preview flag and Ruff prints
  no warning. The inertness recorded here is historical, true of 0.15.13 and
  false of the pinned binary. The case was kept rather than deleted precisely
  so a future release that made the syntax preview-only again would fail it.
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
  (`suppressions.py` reads; `convention.py` judges), so the literal-text
  fixtures import the same function the repository scan uses. Rationale: the
  plan's requirement 4 asks for fixtures fed to that checker; a second judging
  implementation in the test file would prove only that the copy works.
- Decision: put the judgement in `convention.py` rather than leaving it in
  `test_suppressions.py`, where it was first written. Rationale: `reporting.py`
  is the non-test seam the fixtures import, and it was importing a *test*
  module to reach `violations`. Importing `test_suppressions` also evaluates
  its module-level `pytestmark`, which calls `repository_files_present()`, so
  the seam inherited the repository-presence skip condition of a module it does
  not scan. The judgement reads no files, which is what makes it a
  fixture-shaped function rather than a repository one.
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
  already ran the spaced form over `scripts/`. Switching would churn 28
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
- Decision: record the measured size against the scope tolerance and escalate,
  rather than claiming the tolerance was met. Rationale: the plan requires it
  to be recorded, and a reviewer flagged its absence. Measured at commit
  `74af1a6`'s parent, this branch's true fork point, with
  `git diff --numstat 74af1a6~1..50eebeb`. The tolerance's own exception clause
  excludes ExecPlan files, and the generated 691-line `enabled_rules.txt` is a
  measurement artefact rather than reviewable code, so the operative figure
  excludes both: **42 files, 3738 insertions, 78 deletions, 3660 net lines**.
  Counting the ExecPlan but not the inventory gives 43 files, 4803 insertions,
  78 deletions, 4725 net lines. Counting the inventory but not the ExecPlan
  gives 43 files, 4429 insertions, 78 deletions, 4351 net lines. Counting
  everything gives 44 files, 5494 insertions, 78 deletions, 5416 net lines.
  Each basis is stated with its measurement command because an earlier revision
  of this entry attached the 43/4429 figures to the wrong basis; the two
  43-file totals differ only by which artefact is admitted, and swapping them
  is invisible to a reader who does not re-measure. Every basis exceeds both
  bounds — 30 files and 1200 net lines — so the conclusion does not depend on
  which one a reviewer prefers. These are measured at `50eebeb`, the last
  commit before this one; a figure recorded in the same commit that reports it
  can never include itself, so the commit named here is the honest reference
  point rather than a number that changes each time it is written down. The
  overrun is not incidental. The ticket's acceptance criteria require a policy
  contract with positive and negative fixtures, and the contract package alone
  is twenty-one files including its `__init__.py` (twenty modules of actual
  code); the suppression contract spans six of them to stay under Pylint's
  400-line cap, and a provenance contract was added because a rule inventory is
  meaningless unless pinned to the binary that produced it. Trimming the change
  to fit would mean dropping acceptance criteria, so the escalation is the
  honest outcome. It is recorded here for the reviewer to accept or reject; no
  further scope is added pending that decision. Note that
  `git merge-base HEAD main` is *not* the correct baseline: the local `main`
  ref is stale at 2026-07-28, making the diff 95 commits and 144 files of
  unrelated Dependabot work. Only the fork point gives a figure that describes
  this change.
- Decision: repair the two hosted CodeScene findings by refactoring rather than
  suppressing them. Rationale: both files are introduced by this branch, so the
  findings describe code written here, and the repository's precedent
  (`docs/execplans/adopt-nose-code-deduplication.md`) is to refactor. The
  measured repair for `reading.py` is delegation to two private readers rather
  than four copies of the same numpy docstring block; that duplication was
  documentation, not logic, which is why shortening the docstrings alone also
  scored 10.00 — but the logic duplication underneath was real, so both were
  removed. `violations` gained a rule tuple because the six rules were already
  independent; the tuple makes their order and their one-message-per-rule
  contract visible instead of implied by statement order.
- Decision: put the shared Ruff runner in `ruff_run.py` and the shared-line
  fixtures in `test_suppression_shared_line.py`, rather than suppressing
  Pylint's `C0302` or importing one test module from another. Rationale: the
  fixtures took `test_suppression_behaviour.py` to 431 lines against a 400-line
  cap, and the cap is deliberate — `too-many-lines` is explicitly enabled, and
  no `C0302` suppression exists anywhere in the repository. A suppression here
  would hide the very drift the cap exists to catch, in the change that tripped
  it. A test module importing a sibling would also drag the imported module's
  `pytestmark` along with the function, which is exactly the defect this plan
  already fixed once when `reporting.py` imported `test_suppressions`.
  Splitting instead keeps both modules well under the cap (182 and 178 lines at
  `e810082`) and gives the runner one home for the next contract that needs it.

## Outcomes & retrospective

Delivered. The four milestones are complete, and the branch carries more than
forty commits from the base of `74af1a6~1`. Four of the five acceptance
criteria are discharged by something a reader can run. AC4 is discharged only
at the scope this branch can reach: it validates Ruff 0.17.3 on the repaired
baseline, not the refreshed grouped update, which does not yet exist. That
qualification is stated in Milestone 4 and is not a defect to be tidied away
here — see "What remains open" below.

### What a contributor can now do that they could not before

Ask `pyproject.toml` which preview rules this project adopts and get a list of
106 exact codes, each on its own line, rather than an inference from which
prefixes happen to overlap upstream's preview set. Run
`uv run pytest tests/ruff_policy_contract` and have the repository compare its
committed 673-code inventory against what the installed binary actually
resolves, in both directions, naming any code that appeared or disappeared. Read
`convention.py` and find the whole suppression policy as an ordered tuple of
rules with no file I/O. And answer "which Ruff is the gate running" from
`uv.lock` plus the recipe assertion, rather than from whatever `ruff` is first
on `PATH`.

### The measurement that mattered

The migration was accepted on a claim that the resolved rule set is unchanged.
That claim was verified in four cells rather than one, because a single-cell
comparison cannot distinguish a harmless bump from a policy that absorbed the
bump. On the old configuration (`preview = true`, no `extend-select`), 0.15.13
resolved 673 codes and 0.17.3 resolved 683 — the bump silently added ten
preview rules. On the new configuration both resolve 673, with zero added and
zero removed. Holding Ruff at 0.15.13, the policy change moves the set by zero;
holding the new configuration, the bump moves it by zero. Only the
old-configuration bump moves it, which is exactly the defect.

The ten codes were `D421`, `RUF074`, `RUF075`, `RUF077`, `RUF105`, `RUF106`,
`RUF201`, `UP048`, `UP051`, `UP052`. Dependabot #176's CI failure contains
three of them — `D421`, `RUF105`, `UP052` — as 19 errors on `hecate tests`,
with 29 more waiting on `scripts`. The other seven were the quietly-reviewed
part: they arrived inert on this tree and nobody had approved them.

### What the plans did not anticipate

Three findings changed the shape of the work. `ruff: ignore[...]` was a preview
feature on 0.15.13 — a warning and no suppression in stable mode — and became
stable by 0.17.3, which inverted a contract test that had been written as a
negative control. The rule-set inventory is structurally incapable of catching
that: the set of rule *codes* was identical across the change while the meaning
of a *comment* changed under it, so only a fixture running the real binary
could see it. And the directive grammar accepted a rule *name* inside the
brackets, which suppresses in preview mode but matches no code, so a policy
that trusted the mode rather than the code list would have silently disabled
itself in any stable-mode run.

Each of these was found by asserting something that could fail, not by reading
the changelog. The pattern worth carrying forward: when a dependency is treated
as a policy boundary, the contract has to exercise the binary, because the
configuration file describes intent and the binary describes behaviour.

### Cost

The change exceeds the plan's original 30-file / 1200-line tolerance. Counting
non-ExecPlan files, and excluding the generated 691-line `enabled_rules.txt` as
the Decision log does: 42 files, 3738 insertions, 78 deletions, 3660 net lines,
measured at `50eebeb`. Admitting the ExecPlan raises that to 43 files and 4803
insertions; the alternative 43-file basis, which admits the inventory instead,
is 4429 insertions. The overrun was escalated and recorded in the Decision log
rather than trimmed to fit. Most of it is the 106-code adoption list, the
committed inventory, and the contract suite, all of which are the deliverable
rather than incidental.

### Lessons

- A rule-set snapshot proves the set, not the semantics. Both contracts are
  needed and neither substitutes for the other.
- "Unchanged" is a claim about a cell, not about a version pair. The four-cell
  matrix is the minimum that attributes a delta to a cause.
- Extracting the judgement from a test module is what lets the fixtures and the
  repository scan share one implementation; the first placement chose
  convenience over structure and the review caught it. The same lesson recurred
  in the other direction: when shared fixtures outgrew a test module, importing
  the sibling would have carried its `pytestmark` along, so the runner moved to
  a non-test seam instead. Two cases, one rule — a shared test helper belongs
  in a module no test owns.
- Spelling gates run over Markdown only, so a docstring using the -ise form
  survives `make lint` and surfaces only in review. Worth knowing before the
  next review round rather than after it.
- A negative fixture can pass under the defect it was written to catch. The
  inventory reader's own two refusal cases (`"D"`, `"F 401"`) were satisfied by
  the loose pattern and the strict one alike, so they never showed which shape
  ran; only entries that *separate* the two shapes do. The same holds for the
  docstring-cased six-digits fixture: it asserted a refusal that the bound
  gives for the wrong reason, and its name described a shape it never fed.
- CodeScene's duplication detector matches text, not only structure. Four
  functions that each carry the same numpy `Parameters`/`Returns` block are a
  family even when their bodies differ, so a house style that documents every
  parameter of every small reader prices itself into the quality gate. The fix
  is not to stop documenting: it is to document the shared contract once, on
  the helper that actually holds the logic, and let the thin callers say only
  what makes them different.

### Delivered outside this repository

The rule-set delta, the four-cell matrix and the suppression-behaviour pair
were posted to `leynos/shared-actions#588`, which tracks the campaign fixture
for this failure class, rather than building a new runner here. That is Task
4's instruction and the reason the campaign row already exists.

### What remains open

Two things are deliberately unfinished, and neither is a defect this branch can
close.

AC4 is discharged at Ruff scope only. It reads "the refreshed dependency update
passes all existing required gates", and the refreshed update is Dependabot
issue 176 at `b8bb4bdc8a89ac6d8033eb1875b3825f718aadef`, whose `lint-test`
fails in run `42041912849` against a baseline this branch has not been merged
into. This branch validates Ruff 0.17.3 on the repaired baseline; it cannot
validate a grouped update that has not been rebased onto it. That update must
be refreshed after this change lands before its own AC4 claim can be made.

The coverage half of the pragma contract is measured out of band, not in the
suite. `coverage` is not a dependency of this repository, and adding it would
edit `pyproject.toml` and `uv.lock` — the two files the pending grouped update
in issue 176 also edits — so the contract test would collide with the change
whose validation depends on this branch. The suite therefore asserts the two
facts it can assert without the tool: the pragma survives verbatim in the
migrated comment, and Ruff still honours its own directive beside it.

The coverage half was measured directly instead, with the real tool pinned to
an exact version, against the same four comment variants the contract builds.
The driver below is complete: it constructs the fixtures, runs them, and reads
`analysis2` rather than inferring exclusion from `report -m`. Run it from an
empty directory; it writes nothing into the repository.

```bash
COV=(uv tool run --from coverage==7.17.2 coverage)
D=$(mktemp -d); cd "$D"

# The commented statement sits inside a function that drive.py imports but
# never calls, so line 3 genuinely does not execute. The no-comment control is
# what proves it: it reports line 3 as *missing*, which can only happen if the
# line was not run. Exclusion in the other three is therefore attributable to
# the pragma rather than to the line having been executed.
cat > directive_then_pragma.py <<'PY'
x = 1
def never():
    import subprocess  # ruff: ignore[S404]  # Runs it.  # pragma: no cover
PY
cat > pragma_then_directive.py <<'PY'
x = 1
def never():
    import subprocess  # pragma: no cover  # ruff: ignore[S404]  # Runs it.
PY
cat > pragma_only.py <<'PY'
x = 1
def never():
    import subprocess  # pragma: no cover
PY
cat > no_comment.py <<'PY'
x = 1
def never():
    import subprocess
PY
cat > drive.py <<'PY'
import directive_then_pragma, pragma_then_directive, pragma_only, no_comment
PY

"${COV[@]}" run --source=. drive.py

cat > analyse.py <<'PY'
import coverage

probe = coverage.Coverage(source=["."])
probe.load()
for name in ("directive_then_pragma", "pragma_then_directive",
             "pragma_only", "no_comment"):
    _, statements, excluded, missing, _ = probe.analysis2(f"{name}.py")
    print(f"{name:26s} excluded={excluded!s:9s} missing={missing!s:9s} "
          f"line3_excluded={3 in excluded} line3_missing={3 in missing}")
PY
"${COV[@]}" run analyse.py
"${COV[@]}" --version
```

Expected output:

```plaintext
directive_then_pragma      excluded=[3]       missing=[]        line3_excluded=True line3_missing=False
pragma_then_directive      excluded=[3]       missing=[]        line3_excluded=True line3_missing=False
pragma_only                excluded=[3]       missing=[]        line3_excluded=True line3_missing=False
no_comment                 excluded=[]        missing=[3]       line3_excluded=False line3_missing=True
Coverage.py, version 7.17.2 with C extension
Full documentation is at https://coverage.readthedocs.io/en/7.17.2
```

Both directive orders and the pragma-only control report line 3 as excluded
from coverage's statement set, with `missing` empty; the no-comment control
reports the same line as **missing** and not excluded. That last row is what
makes the matrix non-vacuous rather than merely consistent: `missing=[3]` can
only arise for a line that did not execute, so the control demonstrates the
line genuinely never ran. Exclusion in the other three is therefore
attributable to the pragma, not to the line having been executed and so never
reported missing in the first place. That is the coverage reader's own verdict,
not an inference from the comment's text, and it is the four-way matrix the
suite builds, checked against the tool that actually consumes the pragma. What
remains outside the suite is automated regression cover: if a future change
dropped the pragma, the textual assertion would catch it, but if coverage
changed how it parses trailing comments, only a re-run of this probe would.

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
`#140 AC4 -> M4 -> gate transcripts, Ruff scope only; the refreshed-group half
of AC4 is pending #176 and is recorded in Milestone 4 and "What remains open"`;
`#140 AC5 -> M4 -> issue comment on shared-actions#588`.

## Verification plan

Obligations introduced or preserved by this change:

1. *Preview policy is a reviewed artefact.* Invariant: for every tracked
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
   comment in every module the gate checks has explicit codes and a non-empty
   rationale, writes no `noqa` in any spelling Ruff accepts, and has no
   security code in file-level or block form. Method: tokenizer-based contract
   with positive and negative fixtures covering missing rationale,
   whitespace-only rationale, bare `noqa`, `noqa` with a `ruff:` or `flake8:`
   prefix (file-level in either position), upper-case `noqa`, and `S603` inside
   `file-ignore`/`disable`. A second invariant binds the set of files read to
   Ruff's own `--show-files` output, so a directory added to the Makefile
   cannot be linted and unread. Non-vacuity: the negative fixtures are fed to
   the same checker function the repository scan uses, and removing `scripts`
   from the scan's target list names all 17 modules it would have skipped.
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
`enabled_rules.txt` (the reviewed inventory; it carried a
`# ruff-version: 0.15.13` header when this milestone was written and carries
`0.17.3` at the published head, which is the point of the header — it records
which binary the set was reviewed against, so the file changes when the pin
does), `test_reading.py` (reader negative cases), `test_inventory.py` (the
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
statement. The base tree carried 30 `noqa` comments across 12 files; the
migration rewrote the 28 of them that sit in the gate's targets, across 11
files. The two it left are `S310` comments in `scripts/typos_rollout.py`, which
`extend-exclude` keeps out of the gate, so rewriting them would be policy no
gate enforces. An earlier revision of this paragraph said the migration rewrote
30 across 12 and that two remained, which cannot both be true.

Six modules carry the suppression contract, and a seventh holds the runner they
share. `suppressions.py` tokenizes and returns a `Suppression` record with its
line, form, codes, and rationale; it is deliberately judgement-free.
`convention.py` holds the judgement, as an ordered tuple of predicates over
those records that reads no files; one predicate per rule, so a message's
wording, its trigger condition, and the order rules are reported in are each a
separate reviewable thing. `test_suppressions.py` holds only the repository
scan, asking Ruff for `--show-files hecate tests scripts` so an excluded module
is not failed for a comment the gate never reads. At the published head that
command returns **107 files** under the locked Ruff 0.17.3. The three roots
hold 111 tracked Python files; the four the command omits are exactly the
`extend-exclude` entries in `pyproject.toml` — `scripts/typos_rollout.py`,
`scripts/typos_rollout_cache.py`, `scripts/generate_typos_config.py` and
`scripts/tests/test_typos_rollout.py`. An earlier revision recorded 111 here,
which was the tracked count rather than Ruff's, and contradicted itself by
saying `scripts/typos_rollout.py` was absent from a list that included it. The
scan derives the count at run time rather than asserting a constant, because
the repository gains modules faster than this paragraph is edited.
`test_reading_suppressions.py` feeds literal text to the same reader and the
same judgement, which is what makes a passing repository scan mean something.
`test_suppression_behaviour.py` proves the syntax rather than the reading, and
`test_suppression_shared_line.py` proves it survives a comment shared with
another tool.

Non-vacuity was demonstrated by seeding faults. Making `has_reason` always true
failed 6 cases; making the reader return nothing failed 21, including the
repository scan's own non-vacuity test; removing the broad-form rule from
`violations` failed the 3 broad-form cases. The restored tree is 70 passed, and
`uv run ruff check hecate tests scripts` reports `All checks passed!`.

The coverage half of the shared-line contract was measured out of band with
coverage 7.17.2, against the same four comment variants the contract builds. It
is not a suite assertion because `coverage` is not a dependency and adding it
would edit the two files issue 176 also edits; see "What remains open". The
complete reproduction, including fixture construction and the `analysis2` call,
is in "What remains open" above.

```plaintext
directive_then_pragma      excluded=[3]       missing=[]        line3_excluded=True line3_missing=False
pragma_then_directive      excluded=[3]       missing=[]        line3_excluded=True line3_missing=False
pragma_only                excluded=[3]       missing=[]        line3_excluded=True line3_missing=False
no_comment                 excluded=[]        missing=[3]       line3_excluded=False line3_missing=True
```

Both directive orders and the pragma-only control report the line as excluded
from coverage's statement set; the no-comment control reports it as missing and
not excluded, which demonstrates the line really did not execute and so makes
the other three rows attributable to the pragma rather than vacuous. That is
the reader consuming the pragma giving its own verdict, rather than an
inference from the comment's text.

The behaviour fixtures also changed two of the plan's assumptions. The plan
said to run them through Ruff with `--isolated --preview`; on the then-pinned
0.15.13 the `--preview` half turned out to be load-bearing, not decoration, and
got its own case asserting inertness. That case inverted during the 0.17.3
upgrade, when the syntax stabilized — it is now
`test_the_syntax_suppresses_without_preview` and asserts the opposite, keeping
the mode question recorded in both directions rather than only the version the
plan was written against. The second assumption held: the plan implied one
fixture could trip both security codes, but an all-literal vector trips S607
alone and only a vector with a variable element trips S603. Both facts are
recorded in `Surprises & discoveries` because a future maintainer adding a
fixture will otherwise repeat the mistake.

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

Revision 2: sixteenth review pass, during milestone 3. Records the measured
scope against the tolerance and that both bounds are exceeded, with the fork
point the measurement must use. The code change delegates the rule-code shape to
`reading.is_rule_code`, replacing the duplicate definitions in the selector
and suppression contracts, and adds a test-level skip for the Git-dependent
walk. The escalation affects remaining work only in that milestone 4 must not
add scope until the overrun is accepted; milestone 3's acceptance evidence is
unchanged.

Revision 3: pre-assessment bookkeeping at head `9284bb0`. Records the
`typos.toml` refresh and the corrected commit-count and cost figures. No
acceptance evidence, decision or verification obligation changed.

Revision 4: post-assessment corrections. Two defects the completeness
assessment found are fixed. First, the `TestTwoToolsOneLine` fixtures the
`Risks` section promised did not exist; they now do, and the `Risks` entry
names them rather than restating the promise. Second, milestone 3, part one
miscounted the `D421` edits as "six summary lines … and eleven properties" when
the diff rewrote sixteen: five in `hecate/`, four in `scripts/nose_schema.py`,
and seven in the contention test. The count is re-derived from
`git diff 55ce29f..HEAD --unified=0` rather than from grepping the current
tree, which counts unrelated docstrings. Milestone 4 now records AC4 as
Ruff-only validation with the refreshed grouped update pending at #176, so the
acceptance mapping claims exactly what was measured.

Revision 5: post-follow-up corrections. Six defects, all in recorded figures or
scopes rather than in behaviour, found by re-measuring every quantitative claim
against the tree instead of against the previous revision. First, the Decision
log attached the 43-file / 4429-insertion figures to the wrong basis: that is
the exclude-ExecPlan, include-inventory basis, while admitting the ExecPlan and
excluding the inventory gives 43 / 4803. All four bases are now stated together
with their measurements. Second, the retrospective claimed every acceptance
criterion was discharged, contradicting the AC4 narrowing recorded in Milestone
4; it now says four of five, and "What remains open" records both the AC4
dependency and the coverage-pragma gap. Third, the Decision log and the
Milestone 3 retrospective still described the preview-mode case as asserting
inertness, which was true of 0.15.13 and is false of the pinned binary; both
are now marked as historical with the inversion recorded. Fourth, the
suppression-contract module count said four where the enumeration names six
plus the shared runner. Fifth, the Milestone 1 inventory header was described as
`0.15.13`, which was true when written; it now records both versions and why
the header moves with the pin. Sixth, two further counts drifted: the `noqa`
migration is 28 across 11 files, not 30 across 12 (30/12 is the whole base
tree, including the two the migration deliberately left), and the behaviour
scan covers 107 files at the published head under the locked binary, not the 95
measured at the first commit — nor the 111 that a later revision recorded,
which was the tracked file count rather than Ruff's.

Revision 6: closing the coverage question rather than caveating it. The
previous revision narrowed the pragma claim to literal retention after finding
that `coverage` was not importable in the project environment. It is not a
dependency, but it is runnable: `uv tool run --from coverage` supplies it
without touching `pyproject.toml` or `uv.lock`. The four-fixture matrix was
therefore measured with coverage 7.17.2 and `analysis2`, and both directive
orders plus the pragma-only control report the line as excluded while the
no-comment control does not. The measurement is recorded in Milestone 3 and in
"What remains open"; the suite keeps the two assertions it can make without the
tool, because adding the dependency would edit the same two files issue 176
edits.

Revision 7: the review of revision 6 accepted the out-of-band measurement as
manual acceptance evidence and left five corrections. The pinned measurement
command in the Decision log still read `..HEAD` while the figures beside it
were pinned to `50eebeb`; it now names the same commit. The reproduction block
printed the tool version but not the matrix, so it proved nothing a reader
could check; it is now the complete driver, with fixture construction, the
`analysis2` call, and the expected output, pinned with
`--from coverage==7.17.2`. Three counts were still stated as 30 where the
gate's targets hold 28: the Milestone 3 checkbox, the falsification note, and
the decision not to switch comment spelling. The suppression contract was said
to span five modules where its own enumeration names six. The two split modules
were said to be 182 and 152 lines; the second is 176. The behaviour scan said
111 files, which was the tracked count for the three roots rather than Ruff's
`--show-files` output of 107 — the paragraph contradicted itself by saying
`scripts/typos_rollout.py` was absent from a list that included it, and the
four files Ruff omits are exactly the four `extend-exclude` entries. Sizes for
the `noqa` population were re-measured against `55ce29f` and confirm 30 across
12 files in the base tree, 28 across 11 once `scripts/typos_rollout.py` is
excluded.

Revision 8: two corrections from the review of revision 7, the first of which
made the evidence stronger rather than only its wording. The coverage driver
claimed line 2 was never executed, but its `drive.py` imports all four
fixtures, and an import executes the module body: line 2 ran in every fixture,
so `missing=[]` was trivially true and proved nothing. The statement now sits
inside a function the driver imports but never calls, and the no-comment
control reports it as `missing=[3]` — which can only happen for a line that did
not execute. That turns the other three rows from merely consistent into
demonstrably attributable to the pragma, and the matrix is now four-way
non-vacuous instead of three-way plus a control. The driver copied verbatim
from this plan was run end to end and reproduces the recorded output exactly.
Separately, the opening said 0.16.9 added `D421` "and nine others" against a
stated delta of nine; measurement confirms 0.16.9 adds nine rules (`D421`,
`RUF074`, `RUF075`, `RUF077`, `RUF105`, `RUF106`, `RUF201`, `UP048`, `UP051`)
and 0.17.3 adds a tenth, `UP052`, so the phrase is now "and eight others" with
`UP052` named as the tenth rather than left implicit in "again".

Revision 9: two documentation discrepancies from the review of revision 8. The
contract module's docstring still described the out-of-band measurement as
reading line 2, which was correct for the superseded driver and wrong for the
function-wrapped one; and both call sites called the driver's fixtures "the
same four fixtures the contract builds", when the suite imports at module top
level and the driver deliberately does not, so they are the same comment
variants rather than the same files. The module now says so explicitly. The
`typos.toml` note said the final commit leaves the file untouched; the branch
in fact refreshes it as `9284bb0`, which the same document records nine lines
later, so the note now says the regeneration is kept out of the Ruff commits
rather than absent from the branch.

Revision 10: the formal review's first pass at the ready head. Two inline
findings and five failed pre-merge checks, dispositioned as follows.

The inline finding was real: `tests/ruff_policy_contract/ruff_run.py` used the
British `-isable` suffix in a comment, which `typos.toml` maps to the American
`-izable` one. Corrected to the mapped spelling.

Four of the five pre-merge checks were gaps this plan had left open rather than
defects, and each is now closed rather than argued away.

- *Unit architecture* — running and reading are now separate.
  `run_ruff` remains the only function that writes a fixture and starts a
  process; `reported` is a pure parse of the JSON that comes back.
  `test_ruff_run.py` holds it to hand-written reports, including an empty one,
  two diagnostics on a shared row, a null location that must raise rather than
  read as line 1, and a monkeypatched working directory proving it touches no
  path. `diagnostics_with_lines` is now `reported(run_ruff(...).stdout)`, so
  the composition is visible in one line.

- *Testing, end to end* — `test_suppressions.py` gained `TestScanReport`, which
  drives the real scan over literal sources and asserts that the report names
  the offending path and its line, and that a clean module produces no entry.
  Until this case, nothing asserted the shape of the gate's own output.

- *Testing, unit and behavioural* — `test_locked_build.py` builds a throwaway
  uv project under `--offline` and shows the three behaviours the flag is for:
  a matching lockfile syncs, a stale one fails with `--locked` named in the
  message, and neither rewrites the lockfile. Previously the contract only
  asserted that the string `--locked` appeared in the `build` recipe, which is
  a claim about text. The `build` recipe genuinely changed in this branch
  (`uv sync --group dev` to `uv sync --locked --group dev`), so the behaviour
  was untested as well as unchecked.

- *Testing, property* — `test_suppression_properties.py` generates code lists,
  rationales and casings and asserts the breadth rule fires exactly when a
  security code appears in a broad form, that a missing or meaningless
  rationale is reported independently, that a lower-case code is always
  miscased, that reordering codes changes no verdict, and that a directive
  inside a string literal is never read while the same text as a comment is.
  The first run failed, and the failures were the assertions': I had keyed on
  words the messages do not use, and had assumed a lower-case code was
  canonically cased. Both are recorded in the module, because a named case
  written from the same wrong premise would have passed.

- *Developer documentation* — `docs/developers-guide.md` gained "Suppressing a
  Ruff diagnostic", covering the syntax, the rationale, casing, comma-separated
  code lists, the breadth rule for security codes and the shared-line shape.
  `docs/adr-002-four-tier-python-linting.md` gained an addendum recording the
  preview-selection and suppression policies as decisions, which is where a
  reader of the ADR would look for them.

Two further review points were documentation corrections and are applied: the
shared-pragma fixture is now described as a compatibility case rather than a
migrated one, because the base carries exactly one `# pragma: no cover` and it
sits on a line with no suppression; and the four `0.15.13` references in the
contract modules were rewritten to say the measurement was taken on the
then-pinned 0.15.13 and has been re-checked on the pinned 0.17.3.

Revision 11: the head that closed revision 10's checks, `827b92e`, failed CI on
`make check-fmt`. `mdtablefix --wrap` wanted this very section reflowed by
three characters — the paragraph above, rewritten after the last local
`check-fmt` run, not a tool-version difference between here and CI. The local
command reproduces the CI message exactly once the file is re-read, which is
the evidence that separates the two explanations.

The lesson is not "run the gates again". It is that a documentation edit made
*after* a gate has passed invalidates that gate, and that the invalidation is
silent: `mdtablefix` reports a count against a path, and a skimming reader sees
"1 file would be reformatted" and moves on. The corrective commit `fa2dc17`
carries only the reflow, and `make check-fmt`, `make markdownlint` and
`make nixie` were re-run against it rather than inherited from the earlier head.

Revision 12: the second formal review's pass at `364da1c`. Eleven inline
findings, two outside the diff, and three failed pre-merge checks. Every one
was verified against the tree before it was applied; all were still valid.

The two pre-merge checks that asked for behaviour rather than wording were the
substantive ones. *Testing (Unit And Behavioural)* asked for an end-to-end run
of `make build`, not a transcription of its flags, so `test_locked_build.py`
gained `TestTheBuildTarget`: it drives the repository's own recipe through
`make -C <tmp> -f <repo>/Makefile build` against the throwaway project and
asserts a matching lockfile syncs, a stale one fails, and neither rewrites the
lock. That also replaced the `"--locked" in stderr` assertion, which pinned
uv's wording; the control is now the same stale project synced without the
flag, which succeeds and *does* rewrite the lock. The two runs differ in the
flag and nothing else, which is what the old assertion was reaching for.

*Unit Architecture* asked for the side-effecting `diagnostics` and
`diagnostics_with_lines` wrappers to go. They were a second way to reach
`run_ruff` and `reported`, and the two behavioural modules now compose those
two explicitly. `reported` stays the read-only half, and `test_ruff_run.py`
still holds it to hand-written reports with no filesystem contact.

*Testing (Overall)* asked for `_scan_result()` to be drivable from fixtures. It
already was the repository's scan-and-filter, but it hard-coded the gate's path
list and reader, so `TestScanReport` had reimplemented the filter beside it. It
now takes both as parameters: the gate calls it with `checked_modules()` and
`read_module`, and the two cases call it with literal sources, so neither can
pass against a copy.

The remaining findings were wording and structure. `reported` now raises one
`RuffPolicyError` naming the diagnostic it could not read, chaining the decode
or index error as the cause, and the two tests assert the policy error rather
than `TypeError` and `JSONDecodeError`. `_drew` takes
`tuple[Suppression, ...]`. The module and test docstrings in
`test_suppression_properties.py` describe the contract rather than the session
that produced it. The probe's version case now says it measures the
PATH-resolved binary, and the `sys.version_info` assertion, which checked
pytest's interpreter rather than uv's, is gone. The ADR `Date` reads
`2026-08-24, last updated 2026-11-06` with the Dependabot reference as footnote
`[^1]`. The developer guide's two new blocks carry `_Code block 7_` and
`_Code block 8_` captions, and its `-isable` wording now names the mapped word
instead of the mangled suffix.

Revision 13: CodeRabbit's replies to the eleven threads at `cc0e02d`. Ten
confirmed the fix and resolved. One did not, and it was right. Thread
`4489627464` pointed out that `test_the_probe_uses_the_uv_on_path` still said
`_uv` and the build recipe "agree by construction", which is false: the recipe
resolves `uv` through `command -v`, while the test passes `UV={_uv()}` and
therefore *overrides* whatever the recipe would have found. The two agree
because the probe imposes the agreement, not because either resolves the same
way, and `Makefile` line 12 spells the variable `UV ?=`, so a caller's
environment can shadow it regardless.

The docstring now says the override is what holds the two together, and keeps
the one claim the case can actually make: the binary was present and answered.
A resolved thread is not evidence that the point was addressed, so this
revision exists to record that the confirmation above was read rather than
counted.

Revision 14: the third formal review's four findings, at `f4ec916`. Two were
inline; two arrived as pre-merge checks. All four were real, and the two that
mattered most were both cases of a test agreeing with its subject rather than
measuring it.

The first inline finding was a silence. `reported` indexed the decoded report
with `diagnostic["code"]` and `diagnostic["location"]["row"]` and nothing else,
so a report carrying `{"code": null}` or a string `row` decoded, indexed, and
returned: the reader handed back a pair whose members were not the types every
caller compares. The effect was to turn a malformed report into an ordinary
"this code is not in the expected set" result, which is the one outcome the
whole package exists to distinguish from a real absence. `reported` now also
refuses a report that is not a JSON array — a bare object would iterate as its
keys and a `null` or number would raise a raw `TypeError` from the loop header
— and per-entry work moved into `_code_and_row`, which checks each field where
it is read. The four new cases in `test_ruff_run.py` were written first and all
eight rows of the two tables failed against the old reader with exactly the
predicted symptom.

Three of the checks on that helper were themselves findings. Pylint refused the
combined type test at three boolean operators, and `ty` refused to index a
`dict` after `isinstance` narrowing, so the check is now three separate
questions in sequence: code, then location, then row. That is more readable
than the tuple guard it replaced, and the `bool` exclusion that the docstring
explains is stated once, in the one place that asks the question.

The second inline finding was the pair-isolation hazard in the build probe.
`uv sync` removes packages the project does not declare and targets whatever
`UV_PROJECT_ENVIRONMENT` names, so a developer with that variable exported had
their real virtualenv uninstalled when the probe ran. This was reproduced in a
scratch directory before anything was changed: with the variable set, `uv sync`
printed `Creating virtual environment at: <named path>` and left no `.venv` in
the project at all. `_uv_env` now drops that one variable and passes everything
else through, because the probes still need `PATH` to find `uv`. Two cases hold
it, one for `_uv_run` and one for the `build` target, since the recipe reaches
`uv` by a different route.

The pre-merge checks made the two smaller points. The readers in
`provenance.py` and `inventory.py` still read their own files, which meant a
case could not show what the parser does with a continuation or a missing goal
without the repository being edited to carry one; both now take their source as
a parameter, with `_read` and `inventory_text` as the only file boundaries.
`inventory_header` had the same shape and the same fix. The Property / Proof
row then asked for confidence the new walk did not have: `directories_between`
was covered by three hand-written shapes and no relation.
`TestDirectoryDiscoveryProperties` now states the contract over generated path
trees — the result is exactly the distinct ancestors strictly below the root,
sorted — and was mutation-tested twice against `discovery.py`, once to make it
report the root and once to drop the sort, with both caught.

The lesson worth keeping is about where a test can quietly stop measuring. The
reader agreed with every report the repository produced because those reports
were well-formed; the probe agreed with the Makefile because the test imposed
the agreement; the walk agreed with three examples that were chosen by the same
person who wrote the walk. None of these failed, which is exactly why the
pre-existing suite reported 772 passing tests while all four defects were live.

Revision 15: CodeScene on `01075a8`, which caught a regression revision 14
introduced. The rewrite of `reported` moved four sequential guards into
`_code_and_row`, and four guards is cyclomatic complexity 10 — enough for the
Complex Method biomarker, and enough to take the file from a clean 10.00 to
9.69 and fail both "New code is healthy" and the advisory rules gate. The
finding was checked against the previous head rather than taken on trust:
`cs check` scores `f4ec916`'s copy of the file at 10.00 and the committed copy
at 9.68, so this was a regression in a new commit, not a long-standing smell.

The fix splits the reader into `_code_of` and `_row_of`, one field each, with
`_code_and_row` reduced to the mapping guard and two calls. That is also the
shape the two fields want: `location` has to be narrowed before it can be
subscripted at all, so the combined check only worked by re-narrowing inline.
The file is back at 10.00.

Two type-checking details were learned here and are worth recording because
neither is guessable from the code. The repository bans importing
`collections.abc` members directly, so the annotation is written
`cabc.Mapping` — and since it is used only in annotations, the import belongs
inside the `TYPE_CHECKING` block, which is also where `ruff` demanded it move.
And `dict` is invariant in `ty`, so `Mapping[object, object]` will not accept a
value narrowed to `dict[Unknown, Unknown]`; the key type has to be `Any`. The
values stay `object`, since narrowing them is what the per-field checks are for.

The general lesson is that a refactor justified by a lint finding can itself
introduce a health regression, and the health gate is a separate signal from
lint, format and types. All three of those passed on the version CodeScene
rejected.

Revision 16: the fourth formal review's pre-merge Unit Architecture check on
`c18afda`, which failed with five points and all five were valid. The heading
said Unit Architecture; the finding was consistency of the read boundary.

Revisions 14 and 15 separated each parser from the file that holds its text,
but only in `provenance.py`. `inventory_text` and the two pyproject readers
still opened their own files and still raised a raw `OSError`, so a partial
checkout raised `FileNotFoundError` out of two modules and `RuffPolicyError`
out of the third. The fix is one `read_text` in `reading.py`, which is the root
of the package's import graph, with `inventory.py` and `provenance.py` calling
it. `provenance._read` is gone rather than duplicated, and `pyproject_document`
parses `pyproject_text` instead of opening the file a second time.

The decode path stays separate on purpose, and a fourth case asserts it. A file
that is present but malformed is a defect in the file, not a missing one, so
`TOMLDecodeError` is left unwrapped; folding it into `RuffPolicyError` would
make "missing" and "wrong" indistinguishable. Three new cases point each reader
at a directory holding no file and assert `cannot read`. All three raise
`FileNotFoundError` against the pre-fix modules, which was checked by restoring
the old three modules and running the new cases before the fix.

That surfacing straight away hit the module-length cap: `reading.py` grew to
406 lines against a 400 limit. This is the one place the batch needed judgement
rather than a rule. Splitting `read_text` into its own module was
disproportionate — nine importers name `RuffPolicyError`, and moving it is a
separate refactor nothing here needs. Moving the process-running readers into
`ruff_run.py` is genuinely the right long-term home, since that module's own
docstring calls itself "the one function that writes a file and starts a
process", but it changes what every caller imports. So the file was brought
under the cap by tightening the prose the new paragraph had made redundant in
`repository_files_present`, which restated its own Parameters section. It sits
at 399 lines.

The fourth point was a stale reference: `test_provenance.py`'s comment named
`goal_body`, which had been renamed to `recipe_text` two revisions earlier and
no longer existed. It now names `makefile_text` as well, and says the failure
is a `RuffPolicyError` rather than a `FileNotFoundError`, which the new read
boundary makes true.

Revision 17: the approval exchange on `49d038e`, which turned up one factual
correction and one unresolved mechanical blocker. CodeRabbit confirmed on the
published head that it has "no further substantive code, documentation or
acceptance objection" beyond the two recorded owner-scoped items, and that the
five Unit Architecture points are addressed. Two approval requests nevertheless
produced no approval event. This revision records both honestly rather than
treating the prose confirmation as the approval the skill asks for.

The correction: this plan and the PR body describe the grouped update without
naming its Ruff version in most places, but the approval exchange repeated
0.16.9 from issue #140's original 5 October inspection of #129. CodeRabbit
checked the lockfile and reported that #176's current head `15783f3` pins
0.17.3. That is correct, and it was verified directly against `uv.lock` at that
commit: base 0.15.13, #176 0.17.3, this head 0.17.3. The consequence is worth
recording because it sharpens the diagnosis: #176 has already been re-resolved
onto the same Ruff this branch adopts, so its failure is not the stale-binary
case the ticket opened with. It fails because it carries the new binary against
the OLD configuration — `preview = true` with broad `D`/`RUF` selectors — which
is exactly the pair this branch decouples. A rebase onto this branch's
`pyproject.toml` is what makes its own gates meaningful.

The blocker: `reviewDecision` remains `CHANGES_REQUESTED` from review
`5882804580`, submitted against `c18afda`, two commits behind the published
head. That review's substance is spent — its five Unit Architecture findings are
fixed in `cc5bb5b` and confirmed fixed by CodeRabbit twice — but the submission
itself is a historical event that no later commit clears. The repository's
ruleset is named `main-required-checks` and lists exactly one required check,
`lint-test`, with `strict_required_status_checks_policy: false`; there is no
branch protection on `main` at all, so no approval is mechanically required.
That is the distinction this plan already relies on: a stale `CHANGES_REQUESTED`
is a process signal about review convergence, not a mechanical merge gate, and
`mergeStateStatus` reads `CLEAN` because GitHub evaluates the ruleset rather than
the review decision. Convergence itself is satisfied on its own terms — zero
unresolved threads of fourteen, and a reviewer statement that nothing
substantive remains. The mechanical artefact cannot be cleared by this agent,
because dismissing another account's review is not within its authority.
