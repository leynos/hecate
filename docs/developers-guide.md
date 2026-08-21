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

Skylos is provisioned independently at the version pinned in the Makefile. The
scan is limited to dead-code analysis, uses the reviewed `pyproject.toml`
configuration, and neither uploads code nor collects provenance.

Treat each finding as dead code until a runtime caller has been verified.
Remove genuine dead code. When static analysis cannot see an intentional
runtime reference, add a narrow, reasoned named exception to
`[tool.skylos.whitelist.documented]` in `pyproject.toml`:

```toml
[tool.skylos.whitelist.documented]
"symbol" = "Verified runtime caller."
```

The reason must identify the verified runtime caller. Do not add broad
exceptions or baselines; remove an exception when its runtime boundary no
longer exists.
