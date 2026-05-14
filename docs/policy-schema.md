# Heron Policy Schema

This document defines the policy layering used by Heron Core before emitting action plans.

## Evaluation Order

1. `defaults`
2. `global`
3. `severity_rules[severity]`
4. `scoped_rules` matching `service/tier/environment`
5. `metric_rules` matching metric name
6. `action_rules` for each candidate action

Each layer can override:
- `auto_mitigate`
- `escalation_required`
- `require_human_approval`
- `max_consecutive_actions`
- `allowed_actions`
- `denied_actions`
- `escalation_policy`

`allowed_actions` acts as an allow-list when non-empty. `denied_actions` always blocks actions.

## File Location

- Default policy file: `config/policy.yaml`

## Minimal Example

```yaml
version: "2026-04-22"
defaults:
  auto_mitigate: true
  max_consecutive_actions: 2
  allowed_actions: [observe_only, restart_component, escalate_incident]
global:
  max_consecutive_actions: 2
severity_rules:
  sev1:
    auto_mitigate: false
    escalation_required: true
    escalation_policy: page_immediately
scoped_rules:
  - match:
      service: payments-api
      environment: prod
    settings:
      require_human_approval: true
metric_rules:
  - metric_name: cpu_utilization
    settings:
      escalation_required: true
action_rules:
  restart_component:
    action: restart_component
    enabled: true
    require_human_approval: false
```

## Validation

Run:

```bash
make policy-validate
```

or:

```bash
python scripts/policy_validate.py --path config/policy.yaml
```
