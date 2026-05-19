# Episodic migration notes

Episodic's repository-local checker established the first working mechanism:
stdlib `ast` import parsing, module groups, dependency-direction checks, and
package `__init__` re-export expansion. The raw policy reviewed during
implementation defines composition roots, domain ports, application modules,
inbound adapters, and outbound adapters as ordered groups.

## Policy translation

The Episodic `composition_root` group maps to Hecate as a group whose allowed
set includes every declared group:

```toml
[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["episodic.api.runtime", "episodic.worker.runtime"]
allowed = [
  "application",
  "composition_root",
  "domain_ports",
  "inbound_adapter",
  "outbound_adapter",
]
```

The `domain_ports` group remains inward-only:

```toml
[[tool.hecate.groups]]
name = "domain_ports"
prefixes = [
  "episodic.canonical.domain",
  "episodic.canonical.constraints",
  "episodic.canonical.ingestion",
  "episodic.canonical.ingestion_ports",
  "episodic.canonical.entity_protocols",
  "episodic.canonical.history_protocols",
  "episodic.canonical.ports",
  "episodic.canonical.reference_protocols",
  "episodic.canonical.unit_of_work_protocols",
  "episodic.llm.ports",
]
allowed = ["domain_ports"]
```

Application modules may import application and domain-port modules:

```toml
[[tool.hecate.groups]]
name = "application"
prefixes = [
  "episodic.canonical.services",
  "episodic.canonical.ingestion_service",
  "episodic.canonical.profile_templates",
  "episodic.canonical.reference_documents",
  "episodic.generation",
]
allowed = ["application", "domain_ports"]
```

Inbound and outbound adapters can then be declared separately:

```toml
[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = [
  "episodic.api",
  "episodic.worker.tasks",
  "episodic.worker.topology",
]
allowed = ["inbound_adapter", "application", "domain_ports"]

[[tool.hecate.groups]]
name = "outbound_adapter"
prefixes = [
  "episodic.canonical.adapters",
  "episodic.canonical.storage",
  "episodic.llm.openai_adapter",
  "episodic.llm.openai_client",
]
allowed = ["outbound_adapter", "application", "domain_ports"]
```

## Migration checklist

1. Add the translated policy to Episodic's `pyproject.toml`.
2. Keep composition-root prefixes before broader inbound prefixes, because
   group matching is intentionally first-match.
3. Replace the repo-local command with `hecate check`.
4. Use `--format json` only where downstream tooling needs structured
   diagnostics; text output is deterministic for snapshots.
5. Preserve project-specific policy fixtures in Episodic only where they
   document Episodic's intended architecture. General checker semantics should
   live in Hecate's unit, behavioural, and property tests.

## Notes from prior art

Import Linter's forbidden contracts and layers contracts informed the Hecate
schema: forbidden source-to-target concepts become `allowed` group lists,
layered dependency direction becomes ordered group policy, and documented
exceptions become ignore entries with reasons.[^1][^2]

______________________________________________________________________

[^1]: Import Linter forbidden contracts:
    <https://import-linter.readthedocs.io/en/stable/contract_types/forbidden/>.
[^2]: Import Linter layers contracts:
    <https://import-linter.readthedocs.io/en/stable/contract_types/layers/>.
