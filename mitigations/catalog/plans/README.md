# Diagnostics Plan Fragments

This folder contains grouped diagnostics plan fragments, organized to mirror alert grouping in
`bots-terraform/shepherd/shared_modules/t2/alarms`.

- `k8s/` contains Kubernetes alert plans.

`app/services/diagnostics_planner.py` loads `mitigations/catalog/diagnostics_plans.yaml` first,
then merges all `plans/**/*.yaml` fragments (later files override earlier definitions by `runbook_id`).
