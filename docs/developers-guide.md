# Developers' guide

## Linting

Run the complete local lint gate with:

```shell
make lint
```

The target runs Ruff and the managed-PyPy Pylint checks, then performs a
blocking Skylos scan for dead production code in `hecate`. Continuous
integration runs the same `make lint` target, so an unexplained Skylos finding
blocks both local commits and pull requests.

Skylos is provisioned independently at the version pinned in the Makefile. Its
command-only macro runs it under Python 3.14 because Skylos parses source using
its own runtime AST; the pinned runtime prevents phantom findings when the
project uses newer Python syntax. The scan-only macro adds the reviewed
`pyproject.toml` configuration. The scan is limited to dead-code analysis and
neither uploads code nor collects provenance.

Treat each finding as dead code until a runtime caller has been verified.
Remove genuine dead code. When static analysis cannot see an intentional
runtime reference, prefer a narrow, typed entry point in `pyproject.toml`:

```toml
[[tool.skylos.dead_code.entrypoints]]
type = "method"
full_name = ["hecate.module.Class.method"]
reason = "Verified runtime caller."
```

The entry point's fully qualified name and type must identify only the verified
runtime boundary. Use `[tool.skylos.whitelist.documented]` only when no entry
point can describe that boundary. Add a named exception with:

```shell
make skylos-allow SYMBOL=handler REASON="Loaded by plugin registry"
```

The target requires both values to contain at least one non-whitespace
character. Use `SYMBOL`, not `NAME`: Windows Subsystem for Linux injects
`NAME` with the hostname. It dispatches `skylos whitelist` before the symbol
and reason, then records the reason in Skylos's documented allow list. Do not
add broad exceptions or baselines; retain the verified runtime caller's
evidence in the reviewing change and remove an exception when its runtime
boundary no longer exists. The helper holds an ignored repository-local
`.skylos-whitelist.lock` with `flock` while Skylos updates the allow list, so
concurrent contributors cannot interleave its read-modify-write operation.

The Makefile contracts are parsed by the pinned `makeutil` executable in
`tests/test_skylos_lint_contract.py`; `tests/test_skylos_allow_contract.py`
uses a temporary recorder to verify exact shell argument forwarding without
editing `pyproject.toml`. `make test` verifies that the parser is available
before running the test suite. CI installs the same pinned Makeutil revision
before each full pytest suite. To bootstrap that parser locally, run:

```shell
rustup toolchain install nightly-2026-05-28 --profile minimal
RUSTFLAGS="-Zpolonius=next" cargo +nightly-2026-05-28 install \
  --git https://github.com/leynos/makeutil \
  --rev 29fc5a1634ffbaa18a773eed9dff1b2838a45d9c \
  --locked --force makeutil
make test
```
