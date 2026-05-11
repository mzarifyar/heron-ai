# Next Features

Date: 2026-04-23  
Status: Proposed

## 0) K8s Mitigation Hardening (Top Priority)

- [DONE] Ticket-to-cluster pinning for diagnostics execution:
  - Resolve kubeconfig from parsed Jira cluster context.
  - Execute all diagnostics against explicit kubeconfig (avoid accidental current-context execution).
  - Fail safe when cluster context is present but kubeconfig cannot be resolved.
- [DONE] Strong safe-command policy:
  - Replace simple `kubectl` prefix check with stricter allowlist validation.
  - Block shell separators/injection primitives.
  - Keep only explicitly allowed piped post-filters (`grep`/`egrep`/`tail`/`awk`).
- [DONE] SEV4 escalation idempotency:
  - Detect prior escalation for a source ticket and avoid duplicate SEV4 creation.
  - Persist/read escalation linkage through existing ticket context persistence.
- [DONE] Overwatch false-recovery reduction:
  - Track workload-hint continuity (not just original pod name disappearance).
  - Prevent “recovered” status when same workload family remains unhealthy.
- [DONE] Safer invasive scope controls:
  - Add optional namespace/workload scoping for pod deletion pass.
  - Add tunable invasive cap and stronger guards before delete actions.
- [DONE] Verification/escalation coupling hardening:
  - Prevent auto-escalation when verification is disabled/unavailable.
  - Require explicit verification signal before SEV4 creation.
- [IN PROGRESS] Throughput and resilience:
  - [DONE] Add optional Jira worker pool (`CORTEX_JIRA_WORKERS`) for multi-ticket processing.
  - [DONE] Add per-ticket time budget guard (`CORTEX_JIRA_TICKET_MAX_SECONDS`) and explicit timeout evidence.
  - [IN PROGRESS] Improve retries with bounded backoff/jitter and partial-run durability checkpoints.
- [DONE] Formal Jira linking:
  - Add true issue-link relation (not only comments) between source ticket and SEV4 ticket.

## 0.1) Vision Gap Closure Workstream (Current Priority)

- [DONE] Policy-as-law enforcement in mitigation path:
  - Jira mitigation/escalation evaluates policy contract (`policy_service`) per ticket.
  - Diagnostics execute only when policy allows `restart_component`.
  - Escalation executes only when policy allows `escalate_incident`.
  - Policy decision/version are persisted in enrichment for explainability.
- [DONE] Throughput resilience slice:
  - Optional worker pool and ticket time budget reduce long-tail ticket starvation.
  - Defaults remain conservative to preserve current behavior.
- [DONE] Formal escalation linkage:
  - Structured Jira issue linking added in addition to comments.
- [DONE] RBAC/control-plane authority boundaries:
  - Mitigation toggles role-gated by control-plane capabilities.
  - DevOps admin write endpoints enforce role authorization (`x-cortex-role` header or `CORTEX_OPERATOR_ROLE`).

## 1) Controlled Rollout (Diagnostics Execute, Dry-Run)

- Enable diagnostics execution with dry-run only:
  - `CORTEX_DIAGNOSTICS_EXECUTE=true`
  - `CORTEX_DIAGNOSTICS_DRY_RUN=true`
- Observe puller/ingestion behavior for 1-2 hours before moving further.
- Validate stability, noise level, and expected verification outputs.

## 2) Pullers UI Enhancements (Verification + Escalation Visibility)

- Add ticket table visibility for:
  - verification status
  - escalation status
- Goal: reduce need to open each ticket detail panel for routine triage.

## 3) Execution/Audit Persistence in Local DB

- Add local DB tables for diagnostics execution history:
  - run-level execution summary
  - per-step command results and timing
- Keep records queryable for troubleshooting and trend analysis.

## 4) Upgrade Runbook Stubs to Command-Ready Playbooks

- Prioritize these families first:
  - `watchdog*`
  - `cda_model`
  - `caa_patient_scheduling`
- Expand from stubs into richer, executable, validated playbooks.

## 5) Canary Enablement for Jira Lifecycle Mutations

- Enable lifecycle mutations in narrow scope first:
  - single Jira project and/or explicit label filter
- Verify behavior and safety before broader rollout.

## 6) Staged Enablement for Auto SEV-4 Escalation

- Keep auto-escalation disabled until false positives are acceptable.
- Enable with strict project-scope guardrails and audit visibility.

## 7) New findniggs

- We only have 20 explicit mitigation plans but 231 mapped runbook IDs. Most alerts still don’t have a dedicated mitigation.
- Some mappings still point to older/generic IDs (rbk-deployment-health-check, rbk-daemonset-health-check, etc.) while the richer plans we built are under different IDs (rbk-infrastructure-kubernetes-*), so the detailed logic may not be selected.
- Result: many alerts won’t run the specific SAFE/INVASIVE/OVERWATCH behavior you expect, and will fall back to generic behavior.