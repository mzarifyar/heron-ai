# Cortex Mitigations Catalog

This directory houses the runbook-as-code library that maps alarms -> mitigations.
The layout intentionally separates authored content (`runbooks/`) from structured
metadata (`metadata/`) and generated artifacts (`generated/`).

```
mitigations/
├── catalog/        # curated views/groupings
├── generated/      # compiled search indexes, bundles
├── metadata/       # YAML descriptors per runbook
├── runbooks/       # markdown/structured runbooks (authoritative content)
├── templates/      # reusable authoring templates
└── tests/          # validation + schema enforcement
```

Each runbook should provide:

- A stable `id` that matches metadata and registry entries.
- A front-matter header with alarm + ownership data.
- Clear sections for _Symptoms_, _Diagnosis_, _Mitigation Steps_, and _Escalation_.

Use `registry.yaml` to register runbooks and drive automated validation.
