# Cortex Roadmap+ (v2+)

## Goal

Capture follow-on capabilities that build on the core Cortex loop without destabilizing production flows.

## Incident Linking

- Chronicle incidents support `linked_incidents[]`.
- API: `POST /api/v1/chronicle/incidents/{incident_id}/links`
- Intended heuristics (future): shared root-cause tags, correlated metrics, and repeated service/region pairings.

## What-If Simulation (Scaffold)

- Service: `app/services/simulation.py`
- API: `POST /api/v1/chronicle/incidents/{incident_id}/simulations/what-if`
- Current behavior:
  - Produces deterministic simulation envelopes.
  - Never executes actions.
  - Reuses Chronicle timeline evidence and optional alternate action inputs.
- Planned evolution:
  - Replay historical metrics.
  - Run alternate policy variants.
  - Compare estimated blast-radius/MTTR outcomes.

## Auto-Generated Insights (Scaffold)

- Service: `app/services/analytics.py`
- APIs:
  - `GET /api/v1/chronicle/insights/near-misses`
  - `GET /api/v1/chronicle/insights/tags`
- Current outputs:
  - Near-miss incident counts.
  - Top tag trends across incidents/timeline events.
- Planned outputs:
  - Action failure-rate trends.
  - Recurring root-cause categories.
  - MTTR and escalation-latency trends.

## Near-Miss Tracking

- Chronicle marks near-misses when verification status is `fail`, `timeout`, or `escalate`.
- Near-misses are queryable in report summaries and analytics APIs.
- Future enhancement: separate near-miss lifecycle state and review workflow.

## Tagging and Annotation Vocabulary

- Base tags can come from services, annotations, and incident metadata.
- Recommended starter vocabulary:
  - `infra`
  - `deployment`
  - `capacity`
  - `dependency`
  - `network`
  - `config`
- Future enhancement: controlled taxonomy + tag validation in APIs/UI.

## Release Priority

1. Stabilize core ingestion, policy, reflex, verify, and escalate loops.
2. Harden Chronicle timelines + postmortem workflows.
3. Roll out Roadmap+ features incrementally behind control-plane toggles.
