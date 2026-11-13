# Architectural decision record (ADR) 004: Attested, reconciled release pipeline

## Status

Accepted, 2026-11-03. Hecate publishes its sdist and wheel to PyPI as
`hecate-enforce` and attaches the same bytes to the tag's GitHub Release,
reconciling the two destinations per filename so a repeated tag uploads nothing.

## Date

2026-11-03.

## Context and problem statement

The previous `release.yml` built a wheel, uploaded it to the tag's GitHub
Release with `--clobber`, and did not publish to PyPI. Hecate now publishes
`hecate-enforce` to PyPI through Trusted Publishing, and two constraints make a
single linear job insufficient:

- A rebuilt artefact is not guaranteed to be byte-identical to an earlier
  build, so a re-pushed tag cannot assume that a second build of
  `hecate_enforce-<version>-py3-none-any.whl` or
  `hecate_enforce-<version>.tar.gz` matches the first.
- PyPI refuses a second upload of an existing filename, and the pipeline must
  never overwrite a GitHub Release asset either. Both destinations are meant to
  hold exactly the bytes a consumer may already have fetched and verified.

The `--clobber` upload made a re-run cheap, but it broke the invariant that a
downloaded artefact's digest never changes under a fixed filename, and it could
silently replace an asset that an earlier run's attestation described.

The pipeline was also the point where the distribution name had to be settled.
Hecate keeps the Hatchling backend, the `hecate` import package, the `hecate`
console script, `python -m hecate`, and the `[tool.hecate]` configuration
namespace. The distribution published to PyPI is `hecate-enforce`, because the
name `hecate` on PyPI belongs to an unrelated third-party library; the
`hecate-enforce` project name was unregistered when this decision was taken.
The name change is confined to packaging metadata, the release workflow, and
the installation instructions.

## Decision drivers

- No artefact may be silently replaced once published.
- A re-pushed tag must be safe to run again without manual cleanup, except when
  the destinations already disagree, which must fail loudly.
- The job holding the PyPI Trusted Publishing credential must resolve no
  third-party code and hold no other token.
- Each job's permissions must be the minimum needed for its own steps.
- Every release must include a source distribution, because the wheel is built
  from it and consumers need to rebuild from source.
- Publication must be observable after the fact without adding an external
  telemetry service.

## Options considered

1. **Keep the `--clobber` upload and add a plain `uv publish`.** Simple, but an
   interrupted or re-run workflow can replace a previously published asset with
   different bytes under the same filename, defeating the provenance an earlier
   run's attestation described.
2. **Fail the whole workflow whenever a tag has already published anything.**
   Safe, but a partially completed run (for example, PyPI succeeded and the
   GitHub Release upload did not) would need manual recovery for every
   artefact, not only the ones that actually disagree.
3. **Reconcile per filename, with a fixed precedence and no overwrites**
   (chosen). Each filename's canonical bytes are decided once, from whichever
   destination already holds it; each destination is sent only the names it
   lacks; and the workflow fails only when the destinations already disagree on
   a name, which needs a human to remove the offending asset.

## Decision outcome

Adopt per-filename reconciliation with least-privilege jobs, with
`permissions: {}` at the workflow's top level so no job inherits a scope it did
not declare.

### Jobs

- `check-version` (`contents: read`) compares the tag with `pyproject.toml`.
  The tag carries the `v` the declared version does not, so the step strips it
  with `${TAG#v}` in Bash and `scripts/release_version.py` compares the rest as
  an exact string: `v0.2.0b1` matches `0.2.0b1`, and any other spelling fails.
  Only the normalized PEP 440 spelling passes the later archive check, because
  Hatchling writes that form into the archives' metadata and the check compares
  the text it finds with the manifest. The job reports whether the version is a
  pre-release, and every job that attests, uploads, or releases waits on it.
- `build-wheels` (`contents: read`) checks the repository out and runs the
  local `pure-python-wheel` composite action. A plain `uv build` builds the
  sdist first and the wheel from that sdist, so every release also proves the
  sdist is buildable, and both files are uploaded as the `wheels-pure`
  artefact. Hatchling's `packages = ["hecate"]` keeps the wheel's import
  package named `hecate`, and `[tool.hatch.build.targets.sdist]` excludes
  virtual environments: CI creates `.venv-coverage` inside the checkout, and
  the absolute `bin/python` symlink inside it makes the sdist unreadable to
  `uv`, which unpacks the archive to build the wheel from it. The exclusion is
  build configuration rather than an ignore-file entry, so the archive does not
  depend on which files the VCS happens to ignore.
- `attest` (`contents: read`, `id-token: write`, `attestations: write`; needs
  `check-version`, `build-wheels`) collects every wheel and exactly one sdist,
  refuses a run that produced none or more than one, and attests all of them
  with `actions/attest-build-provenance`. It stages the Sigstore bundle as
  `hecate-enforce-<tag>.sigstore.json` and hands the files and the bundle on as
  the `release-dist` artefact. The name depends on the tag alone because the
  release must converge: a name that also encoded the run or its attempt would
  be absent from the release on every re-run, so each re-run would add another
  asset and break the guarantee that a repeated tag uploads nothing. Bytes a
  later job carries over from an earlier run were attested by that run, and
  every run's attestation remains in the repository's attestation store.
- `draft-release` (`contents: write`; needs `check-version`, `attest`) creates
  the tag's GitHub Release as a draft, or reuses it if one already exists, and
  snapshots its current assets. It downloads GitHub's bytes for the names this
  run also built and hands them on as the `release-github-state` artefact,
  because a draft release is visible only to a token that can write contents,
  and `publish-pypi` must not hold one.
- `publish-pypi` (the `pypi` environment; `contents: read` for a sparse
  checkout of `scripts/`, plus `id-token: write`; needs `attest`,
  `draft-release`) holds no GitHub token. It reads PyPI's JSON Simple index and
  stages only the filenames PyPI does not already list, using GitHub's
  carried-over bytes when GitHub already has a name this run rebuilt. It
  uploads the remainder with `pypa/gh-action-pypi-publish` and
  `skip-existing: true`, and skips the upload step entirely when nothing
  remains. The snapshot `draft-release` hands over also records whether the
  release is still a draft. A published release is immutable, so if it lacks a
  name this run built, staging refuses before PyPI changes: uploading that name
  would publish bytes no release for the tag can ever match, and PyPI cannot
  take them back. The remedy is a human one — delete the incomplete release and
  re-run, or upload the missing files by hand — and the run stops with both
  destinations unchanged.
- `publish-release` (`contents: write`; needs `check-version`, `draft-release`,
  `publish-pypi`) first records whether the release is still a draft. Only a
  draft receives uploads: a published release is by definition complete, so a
  re-run — which always offers the bundle it built, even when the release
  already holds that name — uploads nothing and still succeeds, which is what
  makes a repeated tag idempotent. A draft path reads the index, polling until
  it lists every name this run built, then uploads the names the release lacks,
  taking PyPI's bytes through the index's `files[].url` and checking them
  against `files[].hashes.sha256`, plus the run's Sigstore bundle. Both paths
  then verify that every name carries the same SHA-256 on PyPI and on GitHub
  and that the bundle is attached when one can be truthful, and only then
  un-draft the release, with `--prerelease` set from the version check.

### Reconciliation and precedence

`scripts/release_assets.py` decides, once per filename, which destination's
bytes are canonical: PyPI's, if PyPI already has the name; otherwise the GitHub
Release's, if it already has the name; otherwise this run's freshly built and
attested file. Each destination then receives only the names it still lacks.
`scripts/release_index.py` reads and filters the Simple index, so the
workflow's steps keep no filename knowledge of their own. There is no
`--clobber` anywhere in the workflow: nothing is ever overwritten.
`scripts/release_assets_cli.py` wraps this library in the `argparse` interface
`release.yml` calls; the library itself declares no command line.

Reading the publish directory, validating its names, and hashing its files are
all fallible, so each is an explicit query: `State.names()` returns the staged
names or raises, and `State.local_digests()` returns the SHA-256 of each named
file or raises. The decisions themselves are pure functions of the listings
they are given: `plan()` chooses the canonical source, `canonical_digest()`
reports that source's digest, and `attests_shipped_bytes()` judges the bundle
from the three digest mappings alone. `attests_canonical_bytes()` is the thin
boundary that hashes the staged files and hands the result to that policy, so
the rule can be exercised without a filesystem. Each command reads the names
once and passes the same tuple to every decision it makes, so one operation
cannot act on two different listings. A decision therefore never lists the
directory on a caller's behalf, and a listing or hashing failure surfaces where
it happened rather than as an apparently empty plan.

### No-overwrite verification and manual recovery

Before `publish-release` un-drafts the release, it re-reads both the PyPI index
and the release's asset list and confirms every artefact name has an identical
SHA-256 digest on both sides, and that the run's Sigstore bundle is attached
when that bundle describes the bytes the release ships.

The PyPI index is fetched a second time immediately before the check rather
than reused from the start of the job, because PyPI serves it through a CDN
cache that can still omit a file `publish-pypi` has just uploaded; reusing the
earlier copy would report that file as missing from PyPI and leave the release
a draft. That re-fetch does not stop at the first `200`: it repeats, within the
same six-attempt budget, until the listing contains every name this run staged,
and fails the step only when the budget runs out. A cache that is merely behind
therefore delays the release rather than failing it, and the intermediate
misses are logged as plain messages, not error annotations.

The job's first index read polls for the same reason, and it is the more
dangerous of the two: staging decides what the release uploads. A listing that
predates the upload would make a name look absent from PyPI, so the run's
rebuild would be copied into the release in place of PyPI's canonical bytes.
Because GitHub never overwrites an asset, that mistake cannot be repaired by a
re-run; it needs a manual asset deletion. Both reads therefore set
`EXPECTED_PUBLISH`, and the final digest check remains as the independent
confirmation that the two destinations agree.

A name that already differs between the destinations makes `publish-release`
fail and the release stays a draft. Recovery is deliberately manual: an
administrator must delete the offending asset from the GitHub Release (PyPI's
published files can never be deleted) so that a later run's reconciliation can
proceed without ambiguity.

### The `pypi` environment and Trusted Publishing

`publish-pypi` runs under the `pypi` GitHub environment, which is restricted to
tags matching `v*.*.*`, and holds only `contents: read` and `id-token: write`.
It never receives `contents: write`, so it cannot itself create, edit, or
upload to the GitHub Release; that stays entirely in `draft-release` and
`publish-release`. PyPI's Trusted Publisher for the `hecate-enforce` project
names owner `leynos`, repository `hecate`, workflow `release.yml`, and
environment `pypi`, so an upload from any other workflow or environment is
refused. Both settings are prerequisites of the first tag and are recorded in
the [developer guide](developers-guide.md#publishing-a-release).

### The Simple index lookup

The PyPI JSON Simple index is read with an explicit bounded retry loop of at
most six attempts, on a network failure, `429`, or a `5xx` status, because the
runner's `curl` cannot report `%{num_retries}`; the loop counts its own
attempts. A `404` is read as an empty index so a first release can proceed; any
other non-200 status fails the run rather than guessing. That reading is not a
claim about the name: `404` can also be a transient cache miss or a project
whose publisher names a different repository, workflow, or environment. Name
availability is confirmed out of band before the first tag, as the developer
guide describes.

A `200` alone does not establish that the listing is current, because the
response comes through a cache. A caller that sets `EXPECTED_PUBLISH` — both of
`publish-release`'s reads do — spends the rest of that same budget asking until
the listing contains every name in the directory, so the staleness that status
cannot show is retried rather than trusted. The check runs in
`scripts/release_assets_cli.py`, so the workflow keeps no filename knowledge of
its own; its intermediate failures are printed without an Actions error
annotation, because a miss the next attempt repairs is not a failure of the
step.

### Attestations

`attest` generates a build provenance attestation for every wheel and the
sdist. PyPI's Trusted Publishing flow, through `pypa/gh-action-pypi-publish`,
separately signs and uploads a PEP 740 attestation for each file it accepts.
Both are kept: the build provenance attestation covers the run that produced
the bytes, wherever they end up, while the PEP 740 attestation is PyPI's own
record for its index.

A bundle attests exactly the artefacts one run built. The plan chooses each
filename's canonical source independently, so a release can end up with a mixed
set: PyPI's or an existing release asset's bytes for names already published,
and this run's own bytes for names neither destination holds. On a re-run whose
rebuild differs, the published names carry an earlier run's bytes. Attaching
this run's bundle then would put a provenance claim on the release that part of
its own assets contradicts, so `publish-release` withholds the bundle unless
*every* name's canonical bytes are the ones this run built and attested.
Withholding is not a failure: the run's attestation still reaches the
repository's attestation store, and the check requires a bundle only when one
can be truthful. A name whose canonical source reports no digest also withholds
the bundle, because the claim cannot be checked.

### Sdist cardinality on every pull request

The release publishes whichever single `.tar.gz` sits beside the wheel, so a
build that produced none, or two, must fail before tag time. `ci.yml` runs the
same composite action in its own `wheel-build` job and then fails the job
unless exactly one sdist and exactly one wheel are present. It also installs
the built wheel into a clean Python 3.14 environment outside the checkout and
runs `scripts/verify_installed_distribution.py`, which checks both archives'
core metadata and then the installed metadata, `import hecate`,
`python -m hecate --help`, `hecate --help`, and `hecate check` against a
fixture policy. The checks are exercised by
`tests/workflow_contracts/test_ci_wheel_build.py`.

### Observability of a release run

A release is hard to diagnose from a run log alone: several steps read the same
PyPI index, a re-run repeats each one, and the interesting fact is often *which
attempt* answered what. The workflow therefore reports at two levels, and
neither level carries a filename, a URL, a release body, or any other unbounded
value.

`scripts/release_report.sh` is sourced by every step that reads PyPI or the
GitHub Release. It writes one row per PyPI index read to `GITHUB_STEP_SUMMARY`:
the job (`GITHUB_JOB`), the attempt number, the HTTP status class (`2xx`, `3xx`,
`4xx`, `5xx`, or `none`), the outcome (`ok`, `retry`, `failed`, or `skipped`),
and the elapsed seconds. The elapsed time is taken around the `curl` call and
around each `gh release` call, so a slow or retrying read is visible without
reading timestamps out of the log. The same helper emits one structured record
per step outcome on standard error:

```text
release-event job=publish-release step=fetch-index outcome=ok status_class=2xx elapsed_s=1 correlation=1234567890/1
```

The correlation field is `${GITHUB_RUN_ID}/${GITHUB_RUN_ATTEMPT}`. Every
diagnostic the release's steps print goes through the helper's `release_log` or
`release_warn`, so it carries that field too, and `scripts/release_assets.py`
appends the same field to the notices and errors it prints. A line in a run's
log therefore names the one attempt that emitted it, and two attempts of the
same run can be compared rather than guessed at.
`tests/workflow_contracts/test_release_workflow_contract.py` pins the summary
columns, the record fields, the correlation source, and the rule that a step
diagnostic is not a bare `echo`.

This is not the `release-telemetry` action the next section rejects. It adds no
action to the release path, sends nothing to a service, and its records are the
run log and the job summary that GitHub already holds; the summary is cleared
with each attempt, so it describes the current one.

### No telemetry action

cuprum's release pipeline writes a bounded JSONL record per phase through a
local `release-telemetry` composite action. Hecate drops it. The pipeline has
no metric consumer, the records would duplicate what the Actions run log and
the two destinations already show, and the action would be another local action
to review and pin against a release path that must stay small. GitHub's own run
history and the attestation store remain the record of what each run did;
`tests/workflow_contracts/test_release_workflow_contract.py` fails if the
action is reintroduced.

### Stdlib-only release scripts

`scripts/release_assets_cli.py` wraps the importable reconciliation library
`scripts/release_assets.py`, `scripts/release_index.py` reads the Simple index,
and `scripts/release_version.py` compares the tag with the manifest.
`scripts/verify_installed_distribution.py` checks the sdist's `PKG-INFO` and
the wheel's `METADATA` against each other and against `pyproject.toml`, then
checks the wheel the pull-request build installed into a clean environment.
These modules use only the Python standard library, not Cyclopts or Plumbum,
and their entry points run under the runner's preinstalled `python3` rather
than through `uv run`. The verifier has its own reason: it runs with the
runner's interpreter *outside* the environment under test, so it cannot import
anything that environment installs. This is a deliberate, documented exception
to [scripting standards](scripting-standards.md): `publish-pypi` holds the PyPI
OpenID Connect (OIDC) credential and must not resolve any third-party package
while that credential is live. Every network call these scripts might otherwise
make stays in the workflow's own `curl` and `gh` steps, which the scripts only
plan for.

### Workflow hardening

Every action is pinned by commit SHA and every checkout sets
`persist-credentials: false`, including the composite action's. `concurrency`
queues a re-pushed tag behind the running release with
`cancel-in-progress: false`, so a queued run starts from a complete state
rather than finding one destination holding only some of a cancelled run's
names. Every value that reaches a `run:` script does so through an `env:`
entry, as a quoted variable under `set -euo pipefail`;
`tests/workflow_contracts/test_workflow_run_scripts.py` scans every `run` in
every workflow and composite action for a pasted `${{ }}` expression, with one
reviewed exception the shared CV-005 `token.check-step` rule requires.

The composite action's output directory is fixed at `dist` rather than an
input. The shared CV-005 `coverage.lane-hardening` rule reads every
`upload-artifact` path reachable from a pull request, and a caller-supplied
directory cannot be shown to stay outside a coverage lane's workspace, so the
rule would refuse the action once `ci.yml` began calling it.

### Release notes and versioning

Hecate keeps no `CHANGELOG.md`. The tag's GitHub Release is generated from the
merged pull requests, and `docs/migration-hecate.md` records the user-facing
changes a consumer must act on; a hand-maintained changelog would duplicate
both and drift from them. The first release under this pipeline is `0.2.0`, the
next pre-1.0 minor identified by the migration notes, and the tag `v0.2.0`
matches `pyproject.toml` exactly.

## Consequences

- A re-pushed tag is safe to run again: every destination converges on the same
  bytes per filename, and a complete second run uploads nothing.
- A name that already differs between PyPI and the GitHub Release blocks
  `publish-release` and requires a manual GitHub Release asset deletion. This
  is intentional friction rather than an oversight.
- `publish-pypi` never holds a GitHub token, and no job other than
  `draft-release` and `publish-release` can write to the release.
- The distribution is `hecate-enforce` on PyPI while the import package, the
  console script, the `python -m hecate` entry point, and the `[tool.hecate]`
  namespace remain `hecate`.
- The release library and its entry points diverge from the repository's
  Cyclopts-and-Plumbum scripting baseline, confined to modules that run only
  inside `release.yml`, immediately before or alongside the PyPI credential's
  use.
- Publication has no telemetry beyond GitHub's run history, the job summary
  and structured records the release writes, and the attestation store. It has
  no changelog beyond generated release notes and the migration guide.

## Known risks and limitations

- The reconciliation logic is a single point of failure for correctness: a
  defect in `scripts/release_assets.py`'s precedence could choose the wrong
  canonical source. This is mitigated by
  `tests/workflow_contracts/test_release_publish_steps.py`,
  `test_release_github_steps.py`, `test_release_reconciliation.py`,
  `test_release_rerun.py`, and `test_release_workflow_contract.py`, which run
  the scripts against scratch directories and recording `gh` and `curl`
  stand-ins, and pin the job scopes, environment, concurrency, ordering, and
  pinned actions. `test_release_end_to_end.py` runs the job sequence twice and,
  in one case, from a real `uv build`, so the bytes carried through every
  hand-off are the package's own.
- The PyPI Simple index is treated as the source of truth for what PyPI already
  holds; an index outage that returns a non-404, non-2xx status fails the phase
  rather than guessing, which is deliberate but means a PyPI-side incident can
  block a release until it resolves.
- The GitHub `pypi` environment and the PyPI Trusted Publisher are repository
  settings, not code. A release tagged before both exist fails at the upload
  step, which is the intended, loud failure.
- Hecate builds one pure Python wheel, so cross-platform wheel matrices are out
  of scope for this pipeline; the sdist is the artefact that covers other
  platforms.
