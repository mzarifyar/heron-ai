# Cortex-AI Autonomous Alert Handling Spec (Working Note)

Date: 2026-04-22 (America/Los_Angeles)  
Status: Draft working requirements for implementation in `cortex-AI`

## 1) Mission

Implement complete Jira alert handling in Cortex-AI so incoming alert tickets can be:

1. Claimed and tracked by Cortex-AI.
2. Parsed into structured incident context.
3. Mapped to the correct mitigation playbook.
4. Executed and verified automatically when safe.
5. Escalated consistently to human on-call when unresolved.

## 2) Source Repositories and Data Discovery Scope

Primary references to inspect and mine:

- Existing implementation patterns: `~/code/cortex`
- Runbooks source of truth: `$USER/code/oda-runbooks`
- Alarm definitions (initial scope):  
  `$USER/code/bots-terraform/shepherd/shared_modules/t2/alarms`
- Additional context from bots-terraform (realms/regions/clusters/account mapping):  
  `$USER/code/bots-terraform` (all relevant folders)
- Prior runbook-as-code attempts in other folders under `~/code`

Required discovery output:

1. Alarm inventory with normalized key/title.
2. Mapping table: alarm -> runbook (if found).
3. List of alarms with runbooks.
4. List of alarms without runbooks.
5. Region/realm/cluster/account resolution metadata for execution targeting.

## 3) Canonical Ticket Parsing Requirements

Ticket title contract example:

`[US-SHAWNEE-1] [AWS1] [Production] [pc-cluster-24-drz-1] One or more pod is down in the cluster`

Extracted fields:

- `alarm_region_display`: `US-SHAWNEE-1`
- `realm`: `AWS1`
- `environment`: `Production`
- `cluster`: `pc-cluster-24-drz-1`
- `reason`: `One or more pod is down in the cluster`

Normalize additionally:

- `alarm_region_normalized`: lowercase dashed AWS style when possible (example `us-shawnee-1`)
- `account`: derive from cluster/env mapping
- `service_family`: inferred from alarm/runbook taxonomy

Description parsing must extract:

- Runbook URL
- Alarm URL
- Ops Central URL
- Alarm status
- Transition metadata
- Query text
- Dimensions block

## 4) Jira Lifecycle State Machine

Expected state progression for Cortex-owned incidents:

1. `new` -> `claimed`
2. `claimed` -> `in_progress`
3. `in_progress` -> `mitigating`
4. `mitigating` -> `verified` (resolved) OR `failed_to_resolve`
5. `failed_to_resolve` -> `escalated_sev4`

Mandatory Jira actions at claim/start:

- Add processing label (example `cortex-ai-processing`).
- Add audit note/comment with correlation IDs.
- Transition issue to `In Progress`.

Mandatory Jira actions after completion:

- Post attempt summary comment.
- Post verification outcome.
- Link escalation ticket if created.
- Keep source-of-truth traceability in comments and labels.

## 5) Runbook Standardization (Schema)

All runbooks should be converted to one machine-readable contract. YAML preferred.

Suggested schema (v1):

```yaml
schema_version: "1.0"
runbook_id: "rbk-k8s-node-down"
title: "More than one node is down"
alarm_match:
  title_patterns:
    - "More than one node is down"
  query_patterns:
    - "kube_node_alive_status"
scope:
  realm: ["AWS1"]
  environments: ["Production", "Development"]
  services: ["kubernetes"]
inputs:
  required:
    - region
    - cluster
    - alarm_id
  optional:
    - dimensions.node_ip
prechecks:
  - id: "api-reachable"
    command: "kubectl get --raw=/version"
    expect: "success"
mitigations:
  - id: "inspect-node-health"
    type: "command"
    command: "kubectl get nodes -o wide"
  - id: "inspect-failing-pods"
    type: "command"
    command: "kubectl get pods -A | egrep 'CrashLoopBackOff|Error|ImagePullBackOff|Evicted'"
verification:
  success_conditions:
    - type: "alarm_status"
      expect: "OK"
    - type: "workload_health"
      command: "kubectl get pods -A --field-selector=status.phase!=Running"
      expect_empty: true
escalation:
  when:
    max_attempts_reached: true
    verification_failed: true
references:
  runbook_url: "https://..."
  alarm_url: "https://..."
  ops_central_url: "https://..."
notes:
  excluded_human_steps:
    - "manual ssh bootstrap instructions removed from executable path"
```

Conversion rules:

- Keep mitigation core; remove generic setup noise (example SSH how-to).
- Preserve useful links in `references`.
- Fill missing operational steps proactively where safe and justifiable.
- Keep commands parameterized by parsed incident context.

## 6) Alarm -> Runbook -> Mitigation Mapping

Resolution pipeline:

1. Match ticket title against alarm catalog (`bots-terraform` alarm definitions).
2. Resolve canonical alarm key.
3. Match to standardized runbook by title/query patterns.
4. Build execution plan with bounded retries/timeouts.
5. Execute and verify.

If no runbook exists:

- Mark as `no_runbook_available`.
- Create or queue runbook authoring task.
- Escalate to on-call with discovered context.

## 7) Mitigation Execution and Verification Expectations

Cortex-AI should attempt to diagnose and recover at the right layer:

- Service level
- Pod level
- Node level
- Cluster level

Verification must use both when possible:

1. Workload health signals (pod/node/cluster healthy state).
2. Alarm lifecycle (returns to `OK`).

Verification result states:

- `resolved`
- `partially_resolved`
- `unresolved`
- `verification_error`

## 8) Escalation (SEV-4) Contract for Unresolved Incidents

If unresolved after configured attempts, create a SEV-4 Jira ticket with a strict template.

Escalation payload schema (minimum):

```yaml
schema_version: "1.0"
escalation_type: "cortex_auto_escalation_sev4"
original_ticket:
  key: "CDA-12345"
  url: "https://jira.../browse/CDA-12345"
  title: "..."
  body_excerpt: "..."
context:
  region: "us-chicago-1"
  realm: "AWS1"
  environment: "Production"
  cluster: "pc-cluster-23-ord-1"
  alarm_id: "..."
  alarm_url: "..."
  ops_central_url: "..."
runbook:
  id: "rbk-k8s-node-down"
  url: "..."
attempts:
  - step_id: "inspect-node-health"
    command: "kubectl get nodes -o wide"
    status: "success|failed|timeout"
    started_at: "..."
    ended_at: "..."
    error: ""
verification:
  status: "unresolved"
  alarm_state_after: "FIRING"
  workload_state_summary: "..."
suggested_next_actions:
  - "..."
artifacts:
  logs_ref: "..."
  explain_trace_ref: "..."
```

Linking requirements:

- New SEV-4 ticket must include original ticket link.
- Original ticket must include SEV-4 ticket link.
- Both tickets must reference shared correlation ID.

## 9) Housekeeping + Alert Handling Convergence

Housekeeping checks already being added to Cortex-AI should feed alert handling:

- Cluster inventory and health snapshots can be reused during active mitigation.
- Bad pod diagnostics and event tails should attach to Jira comments/escalation context.

## 10) Safety, Authority, and Guardrails

During test mode:

- Destructive operations disabled by default.
- Explicit feature flags required for any deletion/restart/scale action.
- Ticket mutation behavior can be separately toggled, but desired end-state for active mode is:
  - apply processing label
  - transition to `In Progress`

Mandatory auditability:

- Every action, command, output summary, and decision reason must be logged.
- No silent failure paths.

## 11) Discovery Output (Generated)

Generated from `scripts/build_alert_catalogs.py`:

- `documents/alarm_catalog.csv`
- `documents/runbook_catalog.csv`
- `documents/coverage_report.csv`
- `documents/coverage_summary.json`
- `documents/coverage_summary.md`

Current baseline (2026-04-22):

- Total alarms discovered: `780`
- Total runbooks discovered (`oda-runbooks` + converted repos): `826`
- Coverage:
  - `matched_by_ref_path`: `568`
  - `heuristic_title_match`: `9`
  - `ref_path_missing`: `115`
  - `no_runbook_ref`: `88`

Additional historical source inspected:

- `$USER/code/runbooks-as-code/alerts_without_runbooks.txt`
- `$USER/code/runbooks-as-code/shepherd/shared_modules/t2/alarms/**/**/*_alerts.txt`

## 12) Next Course of Action (Execution Order)

### Phase A: Stabilize Alarm->Runbook Mapping

1. Resolve top missing runbook ref paths first (highest impact):
   - `pam/order_type_precision_regression`
   - `pam/order_type_recall_regression`
   - `pam/order_type_proposal_rate_regression`
   - `watchdog/sanity-failures`
   - `watchdog/pre-sanity-failures`
   - `watchdog/post-sanity-failures`
2. Create alias normalization for known typo/path drift (example `kafaka` vs `kafka`).
3. Add explicit ownership metadata for unresolved refs to drive runbook authoring.

### Phase B: Convert Mitigations to Executable Playbooks

1. Start with high-volume families where mapping exists:
   - `k8s`, `max_ambient`, `cda_model`, `services`.
2. Build executable playbooks that separate:
   - safe diagnostics (default on),
   - guarded remediation (feature-flagged).
3. Keep all remediation idempotent and bounded by retries/timeouts.

### Phase C: Closed-Loop Ticket Automation

1. Claim ticket (`processing` label + comment + transition `In Progress`).
2. Parse context from title + description + alarm links/dimensions.
3. Execute playbook, verify with workload and alarm state.
4. If unresolved, create linked SEV-4 escalation ticket with strict schema.

### Phase D: Continuous Gap Closure

1. Generate catalogs in CI/nightly and diff drift.
2. Track two explicit queues:
   - `missing_runbook_ref_path`
   - `no_runbook_ref`
3. Prioritize by ticket frequency from Jira puller telemetry.

## 13) Execution Log (Append-Only)

### 2026-04-22 - Step Tracking Update

- DONE: Added repeatable catalog command `make alert-catalog`.
- DONE: Generated/validated catalogs:
  - `documents/alarm_catalog.csv`
  - `documents/runbook_catalog.csv`
  - `documents/coverage_report.csv`
  - `documents/coverage_summary.json`
  - `documents/coverage_summary.md`
- DONE: Cross-checked additional historical dataset in `runbooks-as-code` for coverage context.
- DONE: Added runbook path normalization + alias hook in `scripts/build_alert_catalogs.py`.
- DONE: Re-ran catalog generation after normalization change and verified output integrity.

Current coverage checkpoint:

- `matched_by_ref_path_normalized`: `568`
- `heuristic_title_match`: `9`
- `ref_path_missing`: `115`
- `no_runbook_ref`: `88`

Trajectory note:

- Normalization plumbing is now in place, but this pass did not reduce total missing counts.
- Next trajectory adjustment is content-level gap closure: create alias entries and/or runbook stubs for highest-frequency missing paths instead of relying only on string normalization.

### 2026-04-22 - Next Active Step

- IN PROGRESS: Build prioritized remediation queue for `ref_path_missing` and `no_runbook_ref` (top families first: `cda_proposed_action_model_qualitative`, `watchdog`, `cda_model`, `k8s`).
- PENDING: Propose first batch of canonical runbook IDs + mapping records for implementation in Cortex-AI mitigation resolver.

### 2026-04-22 - Progress Update

- DONE: Added `documents/gap_backlog.csv` generation (prioritized backlog for runbook coverage gaps).
- DONE: Added normalized runbook path field (`runbook_ref_path_normalized`) into coverage output to support deterministic mapping.
- DONE: Confirmed backlog size `203` rows (`115 ref_path_missing` + `88 no_runbook_ref`).

New findings:

- Highest-impact missing ref groups are strongly concentrated:
  - `pam/order_type_precision_regression` (10)
  - `pam/order_type_recall_regression` (10)
  - `pam/order_type_proposal_rate_regression` (10)
  - `watchdog/sanity-failures` and related variants

Trajectory adjustment:

- Next implementation should produce a first-class mapping artifact (canonical alarm key -> canonical runbook id) and use it in mitigation resolver instead of relying only on raw Terraform runbook strings.

### 2026-04-22 - Mapping Artifact Bootstrapped

- DONE: Created first candidate mapping backlog in `mitigations/catalog/alarm_runbook_candidates.yaml`.
- DONE: Added top `ref_path_missing` groups and top `no_runbook_ref` families with proposed canonical runbook IDs.

Next:

- IN PROGRESS: wire this candidate mapping into a resolver service (`ticket context -> runbook_id`) without enabling destructive mitigations.

### 2026-04-22 - Jira Context Enrichment Upgrade

- DONE: Implemented richer Jira description parsing in `app/services/jira_processor.py` for:
  - `runbook_url`
  - `ops_central_url`
  - `alarm_status_from_ticket`
  - `message_type`
  - `transition_timestamp`
  - `query_text`
  - `dimensions_text`
  - `total_metrics_firing`
- DONE: Extended tests to validate enrichment payload extraction from realistic ticket descriptions:
  - `tests/test_jira_processor_enrichment.py`
- DONE: Verified Jira processor tests pass:
  - `tests/test_jira_processor_enrichment.py`
  - `tests/test_jira_processor_label_mutation_toggle.py`

Trajectory note:

- We now capture enough structured ticket context to drive runbook matching and mitigation planning without manual parsing.

### 2026-04-22 - Deterministic Resolver Wiring

- DONE: Added authoritative mapping file for deterministic resolution:
  - `mitigations/catalog/alarm_runbook_map.yaml`
- DONE: Implemented resolver service:
  - `app/services/runbook_resolver.py`
  - resolution precedence:
    1. `message_to_runbook` (high confidence)
    2. `runbook_ref_to_runbook` (high confidence)
    3. candidate ref/family mapping (medium/low)
    4. deterministic derived IDs from ref/group/message (low)
- DONE: Wired resolver into Jira ingestion enrichment:
  - `app/services/jira_processor.py`
  - new fields added under enrichment:
    - `runbook_id`
    - `runbook_resolution` (`source`, `confidence`, `runbook_ref_path`)
- DONE: Added/updated tests:
  - `tests/test_runbook_resolver.py`
  - `tests/test_jira_processor_enrichment.py`
  - `tests/test_jira_processor_label_mutation_toggle.py`
- DONE: Verified tests pass (`5 passed`).

Trajectory note:

- Resolver is now deterministic and non-destructive as requested.
- Next trajectory is execution planning integration: map `runbook_id` -> safe diagnostic action plan so Cortex can start automated triage without taking ticket-mutating remediation actions.

### 2026-04-22 - Next Active Step

- IN PROGRESS: Build `runbook_id -> safe diagnostics plan` catalog and return it in puller/UI for operator preview.
- PENDING: Add feature-flagged transition from diagnostics-only to mitigation execution.

### 2026-04-22 - Diagnostics Preview Catalog (Completed)

- DONE: Added diagnostics catalog:
  - `mitigations/catalog/diagnostics_plans.yaml`
  - includes runbook-specific safe diagnostic commands and fallback plan.
- DONE: Implemented diagnostics resolver service:
  - `app/services/diagnostics_planner.py`
  - output mode is always `preview_only` (no execution).
- DONE: Wired diagnostics planning into Jira enrichment:
  - `app/services/jira_processor.py`
  - new enrichment field `diagnostics_preview`
  - new run summary metric `diagnostics_planned`
- DONE: Updated Pullers UI ticket detail popup to show:
  - runbook resolution metadata
  - diagnostics plan title/intent
  - numbered diagnostic command list
  - execution mode (`preview_only`)
- DONE: Added tests and verified pass:
  - `tests/test_diagnostics_planner.py`
  - `tests/test_runbook_resolver.py`
  - `tests/test_jira_processor_enrichment.py`
  - `tests/test_jira_processor_label_mutation_toggle.py`
  - Result: `7 passed`

Trajectory note:

- Cortex now deterministically resolves `runbook_id` and presents a safe diagnostics plan per ticket in UI.
- Next step is to add an explicit feature flag and execution pipeline for converting `diagnostics_preview` into automated command runs with guardrails and full audit trail.

### 2026-04-23 - Step 1 (Diagnostics Runner)

- DONE: Implemented diagnostics execution service with guardrails:
  - `app/services/diagnostics_runner.py`
  - supports dry-run vs execute mode, retries, timeouts, command safety check (`kubectl`-only), structured per-step output.
- DONE: Added tests:
  - `tests/test_diagnostics_runner.py`
- DONE: Validation run:
  - `.venv/bin/pytest -q tests/test_diagnostics_runner.py tests/test_diagnostics_planner.py tests/test_runbook_resolver.py`
  - Result: `8 passed`.

### 2026-04-23 - Step 2 (Feature Flags + Safety Gates)

- DONE: Added execution/mutation safety flags in Jira ingestion:
  - `CORTEX_JIRA_MUTATIONS_ENABLED` (default `false`)
  - `CORTEX_DIAGNOSTICS_EXECUTE` (default `false`)
  - `CORTEX_DIAGNOSTICS_DRY_RUN` (default `true`)
  - `CORTEX_DIAGNOSTICS_TIMEOUT_SECONDS` (bounded 5-300)
  - `CORTEX_DIAGNOSTICS_RETRIES` (bounded 0-3)
- DONE: Wired optional diagnostics execution into ingestion summary/enrichment:
  - new summary fields: `diagnostics_executed`, `diagnostics_execute_failures`, gate state fields.
  - new enrichment field when enabled: `diagnostics_execution`.
- DONE: Added tests:
  - `tests/test_jira_processor_diagnostics_execution_flags.py`
  - updated `tests/test_jira_processor_enrichment.py`.
- DONE: Validation run:
  - `.venv/bin/pytest -q tests/test_jira_processor_enrichment.py tests/test_jira_processor_label_mutation_toggle.py tests/test_jira_processor_diagnostics_execution_flags.py tests/test_diagnostics_runner.py`
  - Result: `6 passed`.

### 2026-04-23 - Step 3 (Ticket Lifecycle Automation)

- DONE: Added Jira transition helpers in integration layer:
  - `app/integrations/jira.py`
  - `get_transitions`, `transition_issue`, `transition_issue_by_name`.
- DONE: Added lifecycle automation in ingestion (feature-flagged):
  - start comment + transition to `In Progress`
  - completion comment after diagnostics stage
  - summary counters/errors for lifecycle operations
  - gate: `CORTEX_JIRA_LIFECYCLE_ENABLED` (requires `CORTEX_JIRA_MUTATIONS_ENABLED=true`)
- DONE: Added tests:
  - `tests/test_jira_processor_ticket_lifecycle.py`
- DONE: Validation run:
  - `.venv/bin/pytest -q tests/test_jira_processor_ticket_lifecycle.py tests/test_jira_processor_diagnostics_execution_flags.py tests/test_jira_processor_enrichment.py tests/test_jira_processor_label_mutation_toggle.py`
  - Result: `4 passed`.

### 2026-04-23 - Step 4 (Verification Loop)

- DONE: Added verification stage for each ingested ticket:
  - `app/services/jira_processor.py`
  - evaluates alarm state + execution state and classifies:
    - `resolved`
    - `partially_resolved`
    - `unresolved`
- DONE: Added enrichment payload:
  - `enrichment.verification`
- DONE: Added summary counters:
  - `verification_resolved`
  - `verification_partially_resolved`
  - `verification_unresolved`
  - gate: `CORTEX_VERIFICATION_ENABLED` (default true)
- DONE: Validation run:
  - `.venv/bin/pytest -q tests/test_jira_processor_enrichment.py tests/test_jira_processor_diagnostics_execution_flags.py tests/test_jira_processor_ticket_lifecycle.py tests/test_jira_processor_label_mutation_toggle.py`
  - Result: `4 passed`.

### 2026-04-23 - Step 5 (SEV-4 Escalation)

- DONE: Added unresolved auto-escalation flow (feature-flagged):
  - `app/services/jira_processor.py`
  - gate: `CORTEX_SEV4_ESCALATION_ENABLED` (requires `CORTEX_JIRA_MUTATIONS_ENABLED=true`)
  - creates escalation issue via Jira API
  - posts linking comments on source and escalation tickets
  - stores structured result in `enrichment.escalation`
- DONE: Added summary counters:
  - `sev4_escalations_created`
  - `sev4_escalation_failed`
- DONE: Added tests:
  - `tests/test_jira_processor_sev4_escalation.py`
- DONE: Validation run:
  - `.venv/bin/pytest -q tests/test_jira_processor_sev4_escalation.py tests/test_jira_processor_enrichment.py tests/test_jira_processor_diagnostics_execution_flags.py tests/test_jira_processor_ticket_lifecycle.py`
  - Result: `4 passed`.

### 2026-04-23 - Step 6 (Coverage Closure: Stubs + Registry)

- DONE: Added runbook stubs + metadata for top missing families/refs:
  - `rbk-pam-order-type-precision-regression`
  - `rbk-pam-order-type-recall-regression`
  - `rbk-pam-order-type-proposal-rate-regression`
  - `rbk-watchdog-sanity-failures`
  - `rbk-watchdog-pre-sanity-failures`
  - `rbk-watchdog-post-sanity-failures`
  - `rbk-caa-patient-scheduling-agent`
  - `rbk-cda-model-runtime`
- DONE: Registered all above in:
  - `mitigations/registry.yaml`
- DONE: Validation runs:
  - `.venv/bin/python - <<'PY' ... yaml.safe_load ...` (registry + new metadata)
  - `python3 -m py_compile app/services/diagnostics_runner.py app/services/diagnostics_planner.py app/services/runbook_resolver.py app/services/jira_processor.py app/integrations/jira.py`
  - `.venv/bin/pytest -q tests/test_diagnostics_runner.py tests/test_diagnostics_planner.py tests/test_runbook_resolver.py tests/test_jira_processor_enrichment.py tests/test_jira_processor_diagnostics_execution_flags.py tests/test_jira_processor_ticket_lifecycle.py tests/test_jira_processor_sev4_escalation.py tests/test_jira_processor_label_mutation_toggle.py`
  - Result: `13 passed`.

### 2026-04-23 - Post-Audit Hardening (Mitigations Pipeline)

- DONE: Expanded alarm map generation from seed-only to broad generated coverage:
  - added `scripts/build_alarm_runbook_map.py`
  - regenerated `mitigations/catalog/alarm_runbook_map.yaml` with 224 `runbook_ref_to_runbook` entries.
- DONE: Added 3-pass diagnostics workflow implementation:
  - safe pass (evidence),
  - invasive pass (delete unhealthy pods when enabled),
  - overwatch pass (recovery polling),
  - implementation in `app/services/diagnostics_runner.py`.
- DONE: Persist diagnostics execution artifacts into local DB:
  - added `diagnostics_runs` and `diagnostics_steps` tables in `app/store/local_db.py`,
  - wired persistence from `app/services/jira_processor.py`.
- DONE: Migrated oda-runbooks into Cortex-AI local catalog:
  - added `scripts/migrate_oda_runbooks.py`,
  - imported 441 markdown runbooks into `mitigations/runbooks/oda`,
  - generated 441 metadata files in `mitigations/metadata/oda`,
  - generated index `mitigations/catalog/oda_runbooks_index.yaml`.
- DONE: Validation:
  - `python3 -m py_compile app/services/diagnostics_runner.py app/services/jira_processor.py app/store/local_db.py scripts/build_alarm_runbook_map.py scripts/migrate_oda_runbooks.py app/services/runbook_resolver.py`
  - `.venv/bin/pytest -q tests/test_diagnostics_runner.py tests/test_diagnostics_planner.py tests/test_runbook_resolver.py tests/test_jira_processor_enrichment.py tests/test_jira_processor_diagnostics_execution_flags.py tests/test_jira_processor_ticket_lifecycle.py tests/test_jira_processor_sev4_escalation.py tests/test_jira_processor_label_mutation_toggle.py`
  - Result: `13 passed`.

## 11) Implementation Phases

Phase 1: Discovery and mapping

- Crawl repos/folders in scope.
- Build alarm/runbook coverage lists.
- Normalize region/realm/cluster/account metadata.

Phase 2: Schema and conversion

- Finalize runbook schema.
- Convert first batch of high-volume alarms to executable runbooks.

Phase 3: Execution pipeline

- Implement claim/parse/match/execute/verify loop.
- Implement Jira lifecycle updates and standardized comments.

Phase 4: Escalation automation

- Implement SEV-4 creation template + ticket linking.
- Add “what was tried / what next” consistency checks.

Phase 5: Hardening

- Add retries, idempotency guards, duplicate-claim prevention.
- Add replay/simulation tests and golden test cases.

## 12) Acceptance Criteria (Initial)

1. Cortex-AI can claim a new alert ticket and set it `In Progress`.
2. Parsed context fields are extracted correctly from title/description.
3. Alarm title maps to runbook and mitigation plan.
4. Mitigation execution is auditable and deterministic.
5. Verification checks both workload and alarm states where available.
6. On unresolved incidents, SEV-4 ticket is created with standardized payload.
7. Original/escalation tickets are linked both directions.
8. Coverage report exists for alarms with and without runbooks.

## 13) Detailed Reference

For behavior and implementation details to audit/import:

- `~/code/cortex`
