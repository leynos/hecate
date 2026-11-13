#!/usr/bin/env bash
# Emit the release's step summary and structured records.
#
# `release.yml` sources this file from the steps that read PyPI or the GitHub
# Release. Every diagnostic those steps print carries the run correlation, so a
# log line can be traced to exactly one run attempt, and every PyPI index read
# adds one row to the job summary: job, attempt, HTTP status class, outcome, and
# elapsed seconds. The labels are bounded on purpose. A summary is read by a
# person, and a record is read by nothing that should receive a file name, a
# URL, or a release body.
#
# The workflow sets `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, `GITHUB_JOB`, and
# `GITHUB_STEP_SUMMARY`. A test or a local run that sets none of them still
# works: the correlation says `none`, and the summary is discarded.

release_correlation() {
    printf '%s/%s' "${GITHUB_RUN_ID:-none}" "${GITHUB_RUN_ATTEMPT:-1}"
}

release_status_class() {
    case "$1" in
        2??) printf '2xx' ;;
        3??) printf '3xx' ;;
        4??) printf '4xx' ;;
        5??) printf '5xx' ;;
        *) printf 'none' ;;
    esac
}

# release_log MESSAGE...
# Print one correlated diagnostic on standard output.
release_log() {
    printf 'release correlation=%s job=%s %s\n' \
        "$(release_correlation)" "${GITHUB_JOB:-local}" "$*"
}

# release_warn MESSAGE...
# Print one correlated diagnostic on standard error. A step whose standard
# output carries a protocol routes anything a person reads through this.
release_warn() {
    printf 'release correlation=%s job=%s %s\n' \
        "$(release_correlation)" "${GITHUB_JOB:-local}" "$*" >&2
}

# release_record STEP OUTCOME STATUS_CLASS ELAPSED
# Emit one structured record for a step's outcome. Labels are bounded: the step
# and outcome are literals from the workflow, the class is derived from the
# status or `none`, and the elapsed time is whole seconds.
release_record() {
    printf \
        'release-event job=%s step=%s outcome=%s status_class=%s elapsed_s=%s correlation=%s\n' \
        "${GITHUB_JOB:-local}" "$1" "$2" "$3" "$4" "$(release_correlation)" >&2
}

# release_run STEP COMMAND...
# Run one command, record its outcome and elapsed time, and keep its failure.
release_run() {
    local step="$1"
    shift
    local started=${SECONDS} outcome=ok
    "$@" || outcome=failed
    release_record "${step}" "${outcome}" none "$((SECONDS - started))"
    test "${outcome}" = ok
}

# release_summary_header
# Write the summary's heading and column names once per job. A job's summary
# accumulates across its steps, so the heading is written only when it is not
# there yet.
release_summary_header() {
    local summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
    if ! grep -q '^## Release run$' "${summary}" 2>/dev/null; then
        {
            printf '## Release run\n\n'
            printf 'Correlation `%s`.\n\n' "$(release_correlation)"
            printf '| Job | Step | Attempt | Status class | Outcome | Elapsed (s) |\n'
            printf '| --- | --- | --- | --- | --- | --- |\n'
        } >>"${summary}"
    fi
}

# release_event STEP ATTEMPT STATUS OUTCOME ELAPSED
# Report one PyPI index read: a summary row and a structured record.
release_event() {
    local step="$1" attempt="$2" status="$3" outcome="$4" elapsed="$5"
    local status_class
    status_class=$(release_status_class "${status}")
    release_summary_header
    printf '| %s | %s | %s | %s | %s | %s |\n' \
        "${GITHUB_JOB:-local}" "${step}" "${attempt}" "${status_class}" \
        "${outcome}" "${elapsed}" >>"${GITHUB_STEP_SUMMARY:-/dev/null}"
    release_record "${step}" "${outcome}" "${status_class}" "${elapsed}"
}