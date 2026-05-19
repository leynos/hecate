# BeatCue migration notes

BeatCue's repository-local architecture checker separated import parsing,
package-barrel re-export expansion, policy classification, fixtures, and
Makefile integration. Hecate keeps those concepts as reusable package modules
instead of project-local scripts.

The policy below is translated from `beatcue/architecture/policy.py` in a fresh
Git clone of `git@github.com:leynos/beatcue.git` at commit
`872872d13b5bcf9cdee16fd2c902f1ca1683cf9b`.

## Policy shape

BeatCue can express its current policy without Python code by declaring ordered
groups:

```toml
[tool.hecate]
root_packages = ["beatcue"]
include_external_packages = true
default_rule_id = "ARCH001"

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["beatcue.config"]
allowed = [
  "adapter",
  "application",
  "composition_root",
  "domain",
  "inbound_adapter",
  "infrastructure",
  "outbound_adapter",
]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["beatcue.domain"]
allowed = ["domain"]

[[tool.hecate.groups]]
name = "application"
prefixes = ["beatcue.application"]
allowed = ["application", "domain"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["beatcue.cli", "beatcue.adapters.inbound"]
allowed = ["inbound_adapter", "composition_root", "application", "domain"]

[[tool.hecate.groups]]
name = "outbound_adapter"
prefixes = ["beatcue.adapters.outbound"]
allowed = [
  "outbound_adapter",
  "adapter",
  "application",
  "domain",
  "infrastructure",
]

[[tool.hecate.groups]]
name = "adapter"
prefixes = ["beatcue.adapters"]
allowed = [
  "adapter",
  "application",
  "domain",
  "infrastructure",
  "outbound_adapter",
]

[[tool.hecate.groups]]
name = "infrastructure"
prefixes = ["cmdmox", "cuprum", "cv2", "cyclopts", "librosa", "rich", "transformers"]
allowed = ["infrastructure"]
```

## Migration checklist

1. Add the policy to `pyproject.toml`.
2. Replace the repo-local checker invocation with `hecate check`.
3. Keep `include_external_packages = true` when infrastructure libraries are
   represented as groups.
4. Preserve documented composition-root exceptions as
   `[[tool.hecate.ignore_imports]]` entries with reasons.
5. Move checker-specific fixture coverage to Hecate and keep BeatCue tests for
   project-specific policy examples only.
6. Gate the migration with `hecate check --format text` and, where CI needs
   structured output, `hecate check --format json`.

## Re-export coverage

BeatCue's checker proved that package barrels can hide boundary violations.
Hecate indexes `__init__.py` exports, honours the final literal `__all__`
assignment, falls back to public symbols when `__all__` is absent or
unresolved, and expands statically resolvable star re-exports.

This means an application import such as this remains visible to policy:

```python
from beatcue.adapters import db
```

If `beatcue.adapters.__init__` re-exports `beatcue.adapters.outbound.db`,
Hecate checks both the visible barrel import and the resolved outbound adapter
origin.
