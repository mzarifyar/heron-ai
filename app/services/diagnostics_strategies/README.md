# Diagnostics Strategy Modules

This package keeps runbook-specific execution logic out of `diagnostics_runner.py`.

## Grouping Model

Strategies are grouped by the same domain pattern used in Terraform alarms:

- `k8s.py`: Kubernetes alarms and mitigations

Add new domains as separate files (for example `kafka.py`, `ingress.py`, `prometheus.py`) and wire them from `diagnostics_runner.py` through thin dispatch calls.

## Scope

Each strategy module can own runbook-specific behavior for:

- SAFE pass enrichment
- INVASIVE pass actions
- OVERWATCH pass checks

`diagnostics_runner.py` should keep shared primitives only (shell execution, safety checks, generic fallback behavior, and workflow orchestration).

