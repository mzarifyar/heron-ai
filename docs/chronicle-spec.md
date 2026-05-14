# Heron Chronicle Spec

## Overview

Heron Chronicle is the incident timeline and postmortem system for Heron services. It provides immutable event capture, human annotations, incident linking, and postmortem records that can be audited alongside Explain logs.

## Data Model

- `ChronicleIncident`
  - Identity: `incident_id`, `service`, `environment`, `region`
  - Lifecycle: `status`, `severity`, `started_at`, `updated_at`
  - Relationships: `decision_ids[]`, `linked_incidents[]`, `tags[]`
- `ChronicleTimelineEntry` (append-only)
  - Identity: `event_id`, `incident_id`, `happened_at`
  - Source: `component`, `event_type`, `summary`
  - Correlation: `signal_id`, `decision_id`, `action_id`, `correlation_ids{}`
  - Semantics: `metadata{}`, `tags[]`, `near_miss`
- `ChronicleAnnotation`
  - Human-authored note: `author`, `note`, `tags[]`, `attachments[]`, `created_at`
- `ChroniclePostmortem`
  - Template metadata: `template_version`
  - Structured fields: `summary`, `impact`, `root_cause`, `timeline_summary`
  - Learning fields: `lessons_learned[]`, `follow_up_actions[]`
- `ChronicleReport`
  - Aggregate report fields: `entries[]`, `near_miss_count`, `action_failure_rate`, `tags[]`

## Event Ingestion Contract

All Heron services emit event records to Chronicle through the Chronicle gateway:

- Sense → `ingest.accepted` / `ingest.dropped`
- Insight → `anomaly.detected`
- Core → `decision.created`
- Reflex → `actions.executed`
- Verify → `verification.completed`
- Escalate → `escalation.dispatched`
- Explain → forwards every explain/audit event to Chronicle with `source_component`

This keeps timeline construction centralized and consistent.

## API Contracts

- `GET /api/v1/chronicle/incidents`
  - List incidents (newest-first), with optional filtering by `service`, `severity`, `region`, and time window (`started_after`, `ended_before`).
- `GET /api/v1/chronicle/incidents/{incident_id}`
  - Get incident details, annotations, and postmortem summary.
- `GET /api/v1/chronicle/incidents/{incident_id}/timeline`
  - List immutable timeline entries for one incident, with optional filtering by `severity`, `event_type`, and time window.
- `POST /api/v1/chronicle/incidents/{incident_id}/annotations`
  - Add a human annotation (`author`, `note`, optional tags).
- `PUT /api/v1/chronicle/incidents/{incident_id}/postmortem`
  - Create/update postmortem fields for an incident.
- `GET /api/v1/chronicle/incidents/{incident_id}/postmortem`
  - Read postmortem record.
- `GET /api/v1/chronicle/reports/{incident_id}`
  - Generate an aggregate incident report.
- `GET /api/v1/chronicle/reports/summary`
  - Return high-level incident/near-miss totals.

## UI Integration

- Chronicle UI is served directly from FastAPI at `/` and `/chronicle`.
- UI reads Chronicle APIs under `/api/v1/chronicle/*`.
- UI templates live in `app/ui/templates/`.
- Docker compose should only expose the FastAPI service for Chronicle until a dedicated frontend bundle is introduced.

## Postmortem Templates

- Default `template_version`: `v1`
- Suggested v1 sections:
  - What happened?
  - Customer impact
  - Root cause
  - Recovery timeline
  - Lessons learned
  - Follow-up actions

## RBAC and Auditability

- Annotation roles allowed: `admin`, `operator`, `sre`
- Postmortem edit roles allowed: `admin`, `sre`
- View roles allowed: `viewer`, `operator`, `sre`, `admin`
- Chronicle writes append-only JSONL entries to `data/chronicle.log`.
- Explain writes append-only JSONL entries to `data/explain.log`.
- Correlation IDs are stored in both systems to support cross-audit tracing.
