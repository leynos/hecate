# Architectural decision record (ADR) 003: Adopt the nose duplication gate

## Status

Accepted, 2026-10-11. hecate runs the `nose` duplication gate as part of
`make lint`, adopting the tool-selection decision already made in
`leynos/episodic`, rather than repeating the detector comparison here.

## Date

2026-10-11.

## Context and problem statement

hecate had no automated check for copy-paste duplication. Review caught most of
it, but nothing deterministic did, and the scanning conventions in this
repository put parsing logic in `hecate/` and helper tooling in `scripts/`,
where a duplicated guard or a copied argument-validation block can sit
unnoticed through several review rounds.

Adopting a detector from scratch meant choosing between several tools with
different capability profiles. That comparison had already been run and
recorded: `leynos/episodic` evaluated PyChase 0.1.0, pyscn, and nose 0.20.0
against a benchmark corpus and merged the result as
[ADR-021](https://github.com/leynos/episodic/blob/d9e5ac0d254f375e2986f52d91a3b88c117c833b/docs/adr-021-adopt-nose-duplication-gate.md).
Re-running it here would cost the same work to reach the same conclusion.

## Decision drivers

- One detector, adjudicated once, rather than two repositories with divergent
  duplication policies.
- Deterministic output: a gate that reports differently on identical input is
  not a gate.
- Exceptions that stay reviewable in version control, attached to a reason and
  removable when they stop covering anything.
- A check cheap enough to run on every commit rather than on a schedule.

## Options considered

### Option A: Re-run the detector comparison for hecate

Rejected. The tool-selection evidence does not depend on the application being
scanned. Portable parts are nose's determinism, its output shape, and its cost;
those carry over. What does not carry over is episodic's measured precision,
recall and timings, which this repository makes no claim to.

### Option B: Adopt the corpus, oracle and scorers along with the gate

Rejected. Those artefacts exist to justify the tool choice, which is settled.
Carrying them here would add a benchmark corpus, tuning sweeps, and
adjudication data that this repository would then have to maintain, and a
benchmark CI job to run them.

### Option C: Keep nose's native baseline and ignore files

Rejected. A baseline records what was duplicated, not why it may stay. It also
cannot express "this parallel is intentional", which is the only claim an
exception should make.

### Option D: Run nose behind a reasoned, location-keyed allowlist

Accepted.

## Decision outcome

`make lint` includes `make duplication`, which depends on `make install-nose`.
The installer provisions `nose-cli` at `NOSE_VERSION` into `.tools/nose` with
`cargo-binstall`'s git mode against <https://github.com/corca-ai/nose>, because
the crate is not published on crates.io and binstall has to resolve the GitHub
release artefact. The target is a no-op when the installed binary already
reports the pinned version.

The scan is configured in `[tool.nose]`: roots `["hecate"]`, the three
detection channels as `mode = "syntax,semantic,near"`, a floor of 24
intermediate-language (IL) tokens, `surface = "all"` so families nose keeps off
its dashboard are still adjudicated, and `top = 30` ranked families. Pinning
the channels explicitly keeps a change to nose's defaults from widening or
narrowing the gate silently. Upstream's `--fail-on any` is not applied; the
gate exits 1 on unsuppressed families after adjudicating exceptions.

Exceptions live in `[tool.duplication_gate]` and key on locations rather than
line spans, which churn whenever code above them moves. A key is a path glob
matched with `PurePosixPath.full_match`, optionally suffixed `::name` to
require nose's unit name. An entry names one key (`unit`) or two or more
(`members`), and silences a family only when every location in it matches one
of the entry's keys, so a new copy in an unlisted file still blocks. Entries
the run matches to no family are reported as stale, meaning unmatched in that
bounded scan rather than proven gone; `top` ranks the scan, so an entry must be
re-checked with a widened scan before it is deleted.

Adopting the gate against this repository's own code found two families, both in
`hecate/config.py`, covering the same configuration-table validation. The fix
was an extraction, not an exception: `_read_table_list()` in
`hecate/config_helpers.py` now holds the shared guard, and both call sites use
it. `[tool.duplication_gate]` is empty. No exception was copied from episodic,
and none was needed.

## Consequences

- The gate depends on a pre-1.0, platform-specific binary published through
  GitHub releases, so provisioning needs `cargo-binstall` and a cached
  `.tools/nose` in CI. It is POSIX-only: it uses `fcntl.flock` and POSIX
  directory operations, so the supported developer workflow is POSIX or WSL and
  the blocking run happens on Linux CI. Native Windows is not supported, and no
  claim is made for it.
- Downstream adoption is deliberately stricter than the reference in one
  respect. Episodic's installer allows `cargo-binstall` to fall back to
  compiling nose from source; here `--disable-strategies compile,quick-install`
  makes a missing trusted artefact an explicit provisioning failure instead of
  the start of a costly source build. The installer itself is pinned by version
  and verified against a platform-specific SHA-256 before it runs.
- The gate resolves `NOSE_BIN`, or the repository-local binary, and refuses to
  run when `nose --version` differs from `[tool.nose] version`, so a drifted
  local install cannot quietly change what blocks the build. A missing binary,
  a timeout, a failed command, malformed JSON, or a report of the wrong shape
  all fail closed with exit code 2 and an actionable diagnostic.
- Findings print as `path:start-end ~ path:start-end` families, with the unit
  name appended for each location nose named, alongside the witness kind and
  refactoring value that ordered the family.
- Gating on the top 30 ranked families bounds what the gate adjudicates.
  Duplication valuable enough to enter that ranking blocks the build;
  duplication below it does not, and the bound must be revisited if the ranked
  surface stays saturated. Lower-ranked duplication is not enforced, and the
  gate does not claim it is.
- The exception helper `make duplication-allow` holds an advisory lock beside
  `pyproject.toml` while it rewrites the entries, so concurrent allow commands
  cannot interleave their read-modify-write. The lock coordinates processes
  that follow its protocol; it does not coordinate an unrelated editor.
- The gate's Python modules live in `scripts/` and its entry point
  `scripts/duplication_gate.py` declares the Python 3.14 floor and the pinned
  helper libraries in its uv inline script metadata. The remaining modules are
  plain imports without metadata of their own. The gate therefore runs under an
  interpreter selected explicitly by `make duplication` and by
  `make duplication-test`, not inherited from the application virtualenv.

## Rejected alternatives

- **PyChase 0.1.0.** It reports qualified unit names, which nose does not, but
  it costs a separate Python 3.13 environment and a `PYTHONHASHSEED` pin to
  keep its locality-sensitive hashing stable, and it scans two orders of
  magnitude slower. Its Python 3.13 workarounds are not adopted here.
- **pyscn Type-4 enforcement, even behind an allowlist.** Episodic's
  adjudication found its ranking inverted where it mattered: the corpus's only
  true Type-4 pair scored below control pairs, so no threshold admits the true
  clone while excluding the false parallels.
- **Adopting the benchmark corpus and tuning artefacts.** They justify a
  decision that is already made; maintaining them here is cost without a
  corresponding decision.
- **nose's native baseline and ignore files.** A baseline records what was
  duplicated, not why it may stay, and cannot express an intentional parallel.

## Accepted trade-offs

- nose reports spans without qualified unit names, so allow keys are path globs
  with an optional unit name rather than `path::qualname` pairs. A
  fragment-level finding such as a shared import block carries no name at all,
  and `::name` keys never match it.
- The gate adjudicates a ranked surface, not every reported family. That is a
  deliberate bound on review cost, with the saturation caveat above.
- The tool-selection evidence is reused by reference. This repository asserts
  no measured precision, recall or timing of its own, and the reference
  revision is recorded rather than a floating `latest`.

## Architectural rationale

The decision that needed making twice was which detector to trust. It was made
once, on evidence that does not depend on the application being scanned. What
does depend on the repository — the scan roots, the exceptions, and the fixes
for the duplication it reports — was decided here on this repository's own
findings.
