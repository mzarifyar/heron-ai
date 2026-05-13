# Heron Implementations Guide

A comprehensive reference for all integrations and features in Heron. Documents setup, configuration, and operation for each integration.

**Last updated:** 2026-05-13  
**Status:** Active implementations

---

## Table of Contents

1. [Escalation Channels](#escalation-channels)
   - [Slack](#slack)
   - [PagerDuty](#pagerduty)
   - [Microsoft Teams](#microsoft-teams)
   - [OpsGenie](#opsgenie)
2. [Deployment Integration](#deployment-integration)
   - [ArgoCD](#argocd)
   - [Flux CD](#flux-cd)
3. [Alert Ingestion](#alert-ingestion)
   - [Prometheus / Alertmanager](#prometheus--alertmanager)
   - [CloudWatch](#cloudwatch)
   - [Datadog](#datadog)
4. [Distributed Tracing](#distributed-tracing)
   - [OTLP / HTTP Ingest](#otlp--http-ingest)
   - [Jaeger](#jaeger)
   - [Zipkin](#zipkin)
   - [Tempo](#tempo)
   - [Service Mesh (Istio / Linkerd / Cilium)](#service-mesh)
   - [eBPF / Pixie](#ebpf--pixie)
5. [Infrastructure Discovery](#infrastructure-discovery)
   - [OCI](#oci-oracle-cloud)
   - [AWS](#aws)
   - [GCP](#gcp)
   - [Azure](#azure)
6. [Cluster & Incident Management](#cluster--incident-management)
   - [Kubernetes](#kubernetes)
   - [Jira](#jira)
   - [GitHub Deployment Correlation](#github)
7. [AI / LLM](#ai--llm)
   - [Decide Step (Claude)](#decide-step)
   - [Intelligence Insights](#intelligence-insights)
8. [SLO & Runbooks](#slo--runbooks)
   - [SLO Tracking](#slo-tracking)
   - [Runbook Resolver](#runbook-resolver)
9. [Slack Bot](#slack-bot)
10. [Web Policy Editor](#web-policy-editor)

---

## Escalation Channels

Escalation channels notify teams when manual intervention is needed. Controlled by:
- **Environment variables** (`.env`): API keys, webhooks, tokens
- **Policy gates** (`config/policy.yaml`): `escalation_channels.<channel>.live.<env>`
- **Dry-run modes**: All channels default to `true` (logging only) for safety

### Slack

**File:** `app/integrations/slack.py`

Sends notifications via Incoming Webhooks using Block Kit rich formatting.

#### Setup

1. [api.slack.com/apps](https://api.slack.com/apps) → Create App → Incoming Webhooks → Add → copy URL
2. Add to `.env`:
   ```bash
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
   SLACK_DRY_RUN=true
   ```
3. Flip policy gate when ready:
   ```yaml
   # config/policy.yaml
   escalation_channels:
     slack:
       live:
         staging: true
         prod: false
   ```

#### Example
```python
from app.integrations import slack
result = slack.send_message(target="incidents", message="*SEV2* latency spike", dry_run=False)
```

| Issue | Fix |
|---|---|
| `SLACK_WEBHOOK_URL not configured` | Check `.env` and restart |
| Message not appearing | Check `SLACK_DRY_RUN=true` |
| 403 Forbidden | Regenerate webhook in Slack app settings |

---

### PagerDuty

**File:** `app/integrations/pagerduty.py`

On-call paging via Events API v2. Incidents auto-deduplicate by `dedup_key`.

#### Setup

1. PagerDuty → Services → Integrations → Events API v2 → copy 32-char Routing Key
2. Add to `.env`:
   ```bash
   PAGERDUTY_ROUTING_KEY=your-32-char-key
   PAGERDUTY_DRY_RUN=true
   ```
3. Flip policy gate when ready:
   ```yaml
   escalation_channels:
     pagerduty:
       live:
         staging: true
         prod: false
   ```

**Severity mapping:** `sev1→critical, sev2→error, sev3→warning, sev4→info`

#### Example
```python
from app.integrations import pagerduty
pagerduty.trigger_incident(target="ops", message="DB pool exhausted", severity="sev2",
                           service="payment-processor", incident_id="INC-001", dry_run=False)
pagerduty.resolve_incident(incident_id="INC-001", dry_run=False)
```

---

### Microsoft Teams

**File:** `app/integrations/teams.py`

Sends Adaptive Cards (v1.4) via Incoming Webhooks. Cards include severity colour coding, structured metadata, and a "View in Chronicle" action button.

#### Setup

1. Teams channel → `···` → Connectors → Incoming Webhook → Configure → copy URL
2. Add to `.env`:
   ```bash
   TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
   TEAMS_DRY_RUN=true
   ```
3. Flip policy gate:
   ```yaml
   escalation_channels:
     teams:
       live:
         staging: true
         prod: false
   ```

**Severity colours:** `sev1→red (attention), sev2→orange (warning), sev3→orange, sev4→green`

#### Example
```python
from app.integrations import teams
teams.send_message(target="#ops", message="Connection pool at 94%", severity="sev2",
                   service="payment-processor", incident_id="INC-002",
                   chronicle_url="http://heron/chronicle/INC-002", dry_run=False)
```

---

### OpsGenie

**File:** `app/integrations/opsgenie.py`

Creates alerts via OpsGenie Alerts API v2. **Note:** OpsGenie signups discontinued June 2025 — for existing accounts or JSM Premium only.

#### Setup

```bash
OPSGENIE_API_KEY=your-api-key
OPSGENIE_DRY_RUN=true
# OPSGENIE_API_URL=https://api.eu.opsgenie.com/v2/alerts  # EU region
```

**Priority mapping:** `sev1→P1, sev2→P2, sev3→P3, sev4→P4`

---

## Deployment Integration

### ArgoCD

**File:** `app/integrations/argocd.py`

Rollback and sync ArgoCD applications via REST API v1. Used by the Reflex executor when action type is `argocd_rollback` or `argocd_sync`.

#### Setup

1. ArgoCD UI → Settings → Accounts → Generate Token
2. Add to `.env`:
   ```bash
   ARGOCD_SERVER_URL=https://argocd.example.com
   ARGOCD_TOKEN=eyJhbGci...
   ARGOCD_INSECURE=false     # set true for self-signed certs
   ARGOCD_DRY_RUN=true
   ```
3. Label your apps in Git so Heron can find them by service name:
   ```yaml
   metadata:
     labels:
       heron-service: payments-api   # must match Heron service name
   ```
4. Enable in `config/actions.yaml` and `config/policy.yaml`:
   ```yaml
   # policy.yaml
   live_execution:
     enabled: true
     per_action:
       argocd_rollback: true
   ```

#### How it works

- `argocd://rollback/{service}` → `POST /api/v1/applications/{app}/rollback`
- `argocd://sync/{service}` → `POST /api/v1/applications/{app}/sync`
- Service-to-app matching: app name match OR `heron-service` label match

#### Example
```python
from app.integrations import argocd
app = argocd.find_app_for_service("payments-api")  # returns "payments-api" or None
argocd.rollback(app, revision=0, dry_run=False)    # revision=0 = previous
argocd.sync(app, dry_run=False)
```

---

### Flux CD

**File:** `app/integrations/flux.py`

Trigger reconciliation via Flux notification receiver webhook, or via `flux`/`kubectl` CLI.

#### Setup

```bash
# Option A: Webhook receiver (preferred)
FLUX_WEBHOOK_URL=http://flux-receiver.flux-system.svc/hook/<token>
FLUX_WEBHOOK_TOKEN=<token>
FLUX_NAMESPACE=flux-system
FLUX_DRY_RUN=true

# Option B: kubectl/flux CLI (fallback — no extra setup)
# Ensure kubectl + flux CLI are in PATH
```

Enable in policy:
```yaml
live_execution:
  per_action:
    flux_reconcile: true
```

#### Operations

- `flux://reconcile/{resource}` → triggers reconciliation
- `flux://suspend/{resource}` → suspends HelmRelease/Kustomization (stops Flux overwriting a Heron fix)

#### Create webhook receiver in cluster
```yaml
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Receiver
metadata:
  name: heron
  namespace: flux-system
spec:
  type: generic
  secretRef:
    name: webhook-token
```

---

## Alert Ingestion

Alert pullers run on a configurable schedule and push signals into the Sense → Insight → Decide → Act loop.

### Prometheus / Alertmanager

**File:** `app/services/pullers/prometheus_puller.py`

Pulls firing alerts from Alertmanager and optionally scrapes Golden Signal metrics from Prometheus.

#### Setup

```bash
PROMETHEUS_ALERTMANAGER_URL=http://alertmanager:9093
PROMETHEUS_URL=http://prometheus:9090          # optional — for metric scraping
PROMETHEUS_AUTH_TOKEN=Bearer-token             # optional
PROMETHEUS_BASIC_USER=user                     # alternative to token
PROMETHEUS_BASIC_PASS=pass
PROMETHEUS_TIMEOUT_SECONDS=20
PROMETHEUS_EXTRA_QUERIES=kafka_lag:kafka_consumer_group_lag:job  # custom PromQL
```

```yaml
# config/pullers.yaml
sources:
  prometheus:
    enabled: true
    interval_seconds: 30
```

**Default PromQL queries scraped:** error_rate, latency_p99_ms, cpu_utilization, memory_utilization

---

### CloudWatch

**File:** `app/services/pullers/cloudwatch_puller.py`

Pulls firing CloudWatch Metric Alarms and active AWS Health events.

#### Setup

```bash
AWS_REGION=us-east-1
# Credentials auto-discovered via instance profile, env vars, or ~/.aws/credentials
AWS_ACCESS_KEY_ID=...          # optional — prefer instance profile on EC2
AWS_SECRET_ACCESS_KEY=...
CLOUDWATCH_NAMESPACES=AWS/EC2,AWS/RDS,AWS/EKS   # optional — filter namespaces
```

```yaml
# config/pullers.yaml
sources:
  cloudwatch:
    enabled: true
    interval_seconds: 60
```

**What it pulls:** ALARM-state Metric Alarms + active AWS Health events across configured namespaces.

---

### Datadog

**File:** `app/services/pullers/datadog_puller.py`

Pulls firing Monitors (Alert/Warn/No Data state) and alert events from the Datadog API.

#### Setup

```bash
DATADOG_API_KEY=dd-api-...
DATADOG_APP_KEY=dd-app-...
DATADOG_SITE=datadoghq.com   # or datadoghq.eu, us3.datadoghq.com
```

```yaml
# config/pullers.yaml
sources:
  datadog:
    enabled: true
    interval_seconds: 60
```

**Service extraction:** from DD tags (`service:my-svc`) on each monitor.

---

## Distributed Tracing

All tracing adapters write `ServiceEdgeMetric` rows that power the live service map and dependency graph. Enable the scheduler in `config/pullers.yaml`:

```yaml
sources:
  tracing:
    enabled: true
    interval_seconds: 30
```

### OTLP / HTTP Ingest

**File:** `app/api/routers/otlp.py`

Receive OTLP/HTTP JSON traces and metrics directly — no OTel Collector needed.

#### Setup

Point your apps at Heron:
```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://your-heron-host
OTEL_EXPORTER_OTLP_PROTOCOL=http/json
```

**Endpoints:**
- `POST /otlp/v1/traces` — traces → service edges → ServiceEdgeMetric
- `POST /otlp/v1/metrics` — OTLP gauge/sum metrics → Signal → Sense pipeline
- `POST /otlp/v1/logs` — acknowledged, not yet processed

Optional cluster label: `X-Heron-Cluster: my-cluster`

---

### Jaeger

```bash
JAEGER_URL=http://jaeger:16686
```

Heron queries `/api/services` then `/api/traces` per service over the last 5 minutes. Extracts parent→child span relationships to build service edge latency data.

---

### Zipkin

```bash
ZIPKIN_URL=http://zipkin:9411
```

Queries `/api/v2/traces`, extracts `localEndpoint.serviceName` from each span.

---

### Tempo

```bash
TEMPO_URL=http://tempo:3200
```

Queries `/api/search` then `/api/traces/{id}` (OTLP JSON format).

---

### Service Mesh

```bash
MESH_PROMETHEUS_URL=http://prometheus:9090   # with Istio/Linkerd metrics scraped
MESH_TYPE=auto    # auto | istio | linkerd | cilium
```

Auto-detects mesh type. Queries Prometheus for:
- **Istio:** `istio_request_duration_milliseconds_bucket`, `istio_requests_total`
- **Linkerd:** `response_latency_ms_bucket`, `response_total`
- **Cilium:** `hubble_flows_processed_total`

---

### eBPF / Pixie

```bash
PIXIE_API_KEY=px-api-...
PIXIE_CLUSTER_ID=...
PIXIE_ENABLED=true
```

Runs a PxL script to capture HTTP/gRPC/DB latency between pods with zero code changes. Falls back to a realistic 10-edge demo dataset when SDK unavailable or credentials not set — the service map is always populated.

---

## Infrastructure Discovery

The Discovery page (`/discovery`) scans cloud accounts and produces a coverage map showing which resources are monitored, partially monitored, or unmonitored. All clouds fall back to a realistic 12-resource demo scan when credentials aren't configured.

### OCI (Oracle Cloud)

```bash
OCI_TENANCY_OCID=ocid1.tenancy.oc1...
OCI_USER_OCID=ocid1.user.oc1...
OCI_FINGERPRINT=xx:xx:...
OCI_KEY_FILE=/path/to/key.pem
OCI_REGION=us-ashburn-1
OCI_COMPARTMENT_ID=ocid1.compartment.oc1...
```

**Resources scanned:** Compute instances, Autonomous Databases, OKE clusters, Load Balancers.  
**Coverage check:** OCI Monitoring alarms per namespace.

---

### AWS

```bash
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012    # optional display only
# Credentials via instance profile (preferred on EC2) or:
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

**Resources scanned:** EC2, RDS, EKS clusters, ALB/NLB, Lambda.  
**Coverage check:** CloudWatch alarm dimensions per resource.

---

### GCP

```bash
GCP_PROJECT_ID=my-project-123
GCP_REGION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json   # or use `gcloud auth application-default login`
```

**Resources scanned:** Compute Engine, Cloud SQL, GKE, Global Forwarding Rules (LBs), Cloud Functions.  
**Coverage check:** Cloud Monitoring alerting policies.

---

### Azure

```bash
AZURE_SUBSCRIPTION_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_RESOURCE_GROUP=my-rg    # optional — scans all RGs if unset
# Auth via: az login | service principal env vars | Managed Identity (auto)
```

**Resources scanned:** VMs, Azure SQL, AKS, Load Balancers, Function Apps.  
**Coverage check:** Azure Monitor metric alert rules by resource ID.

---

## Cluster & Incident Management

### Kubernetes

**File:** `app/integrations/kubernetes.py`

Direct `kubectl` command execution for diagnostics and remediation.

```bash
HERON_KUBE_CLUSTER=my-cluster   # optional — resolves kubeconfig automatically
```

**Operations:** `rollout restart`, `rollout undo`, `delete pod`, `get deployment`, pod logs.

---

### Jira

**File:** `app/integrations/jira.py`

Ingests tickets as incidents and creates escalation tickets.

```bash
JIRA_BASE_URL=https://your-org.atlassian.net/rest/api/2
JIRA_BEARER_TOKEN=your-api-token
JIRA_PROJECT_KEY=OPS
```

```yaml
# config/pullers.yaml
sources:
  jira:
    enabled: true
    interval_seconds: 60
```

---

### GitHub

**File:** `app/api/routers/github.py`

Receives push/deployment/deployment_status webhooks and correlates deployments with incidents. When a new incident opens, Heron looks back 30 minutes and adds a "deploy correlation" timeline entry in Chronicle if a matching deployment is found.

#### Setup

1. GitHub repo → Settings → Webhooks → Add webhook
2. Payload URL: `https://your-heron-host/webhooks/github`
3. Events: Pushes, Deployments, Deployment statuses

```bash
GITHUB_WEBHOOK_SECRET=your-secret
GITHUB_DEFAULT_ENV=production
```

---

## AI / LLM

### Decide Step

**Files:** `app/services/ai/decision_advisor.py`, `app/services/ai/provider.py`

The Decide step uses Claude Sonnet 4.6 to reason over incident context — signal data, Chronicle history, Learn scores, service dependencies — and return a ranked action plan with written rationale. Falls back to the rule-based engine if the LLM is unavailable.

#### Setup

```bash
HERON_AI_PROVIDER=anthropic          # anthropic | openai | ollama
HERON_AI_API_KEY=sk-ant-...
HERON_AI_MODEL=claude-sonnet-4-6     # default
HERON_AI_MAX_TOKENS=1024
# For Ollama:
# HERON_AI_BASE_URL=http://localhost:11434
```

The LLM receives: signal context, recent signals (30m), Chronicle incident history (90d), action confidence scores from the Learn loop, available actions from `config/actions.yaml`, policy constraints, and service dependency graph (upstream/downstream).

---

### Intelligence Insights

**File:** `app/services/ai/insight_generator.py`

On-demand: `POST /api/v1/dashboard/intelligence/generate`  
Rate-limited to once per hour. Queries Chronicle (incidents, outcomes, near-misses), builds a structured prompt, calls Claude Sonnet 4.6, and writes results to the `Recommendation` table.

Returns three sections:
- **Recommendations** — service+action pairs with evidence and suggested policy changes
- **Risks** — services approaching threshold breach based on near-miss trends
- **Patterns** — cross-service recurring patterns

**Trigger from UI:** Intelligence page → "Generate Insights" button.

---

## SLO & Runbooks

### SLO Tracking

**Files:** `app/services/slo.py`, `app/api/routers/slo.py`  
**Page:** `/slo`

Define SLOs per service and track error budget burn rate from Signal data.

#### Concepts

```
Error budget = (1 - target) × window_seconds
Burn rate    = observed_error_rate / allowed_error_rate
  1× = nominal consumption (budget lasts exactly the window)
  5× = budget exhausted in window/5 (6 days on a 30d window)
Status: healthy (<25% consumed) → warning → critical → exhausted
```

#### API

```bash
# List SLOs
GET /api/v1/slo

# Create SLO
POST /api/v1/slo
{"service":"payment-processor","name":"Payment SLO","metric_name":"error_rate","target":0.9995,"window_days":30}

# Compute all burn rates
GET /api/v1/slo/burn        # auto-seeds 8 default SLOs on first call

# Burn history for a single SLO
GET /api/v1/slo/{id}/history
```

#### Default SLOs (auto-seeded)

| Service | SLO | Target |
|---|---|---|
| api-gateway | API Gateway Availability | 99.9% |
| payment-processor | Payment Success Rate | 99.95% |
| auth-service | Auth Service Availability | 99.99% |
| checkout-service | Checkout Success Rate | 99.9% |

---

### Runbook Resolver

**File:** `app/services/runbook_resolver.py`  
**Page:** `/slo` (Runbook panel)

Indexes runbooks from local markdown files and Confluence, then surfaces the most relevant ones when a new incident opens in Chronicle.

#### Setup

**Local markdown:**
```bash
RUNBOOK_DIR=docs/runbooks    # default — create .md files here
```

File naming hints: `payment-processor-connection-pool.md` — service name in filename is detected automatically.

**Confluence:**
```bash
CONFLUENCE_BASE_URL=https://your-org.atlassian.net
CONFLUENCE_TOKEN=your-api-token
CONFLUENCE_SPACE=OPS          # space key
```

Only pages with "runbook", "playbook", "sop", or "incident" in the title are indexed.

#### Trigger indexing

```bash
POST /api/v1/runbooks/index
```

Or click "Re-index" in the SLO & Runbooks page.

#### Chronicle integration

When a new incident opens, Heron automatically:
1. Scores all indexed runbooks by service + keyword overlap
2. Adds a `runbook.matched` timeline entry with top 3 matches and URLs

#### Search API

```bash
GET /api/v1/runbooks/search?service=payment-processor&metric=connection_pool_pct&severity=sev2
```

---

## Slack Bot

**File:** `app/api/routers/slack_bot.py`

Interactive slash commands and button clicks. Requires a public HTTPS URL (use ngrok for local dev).

#### Setup

1. [api.slack.com/apps](https://api.slack.com/apps) → your existing app (or create new)
2. **Slash Commands** → Add `/heron` → URL: `https://your-host/slack/commands`
3. **Interactivity** → Enable → URL: `https://your-host/slack/interactive`
4. **OAuth & Permissions** → Bot scopes: `commands`, `chat:write`, `chat:write.public` → Reinstall
5. Copy Bot Token and Signing Secret

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
```

#### Commands

| Command | What it does |
|---|---|
| `/heron status` | Active incidents + weekly summary |
| `/heron incidents` | Last 5 incidents with action buttons |
| `/heron approve <decision_id>` | Approve and execute a pending action |
| `/heron reject <decision_id>` | Reject a pending action |
| `/heron help` | Command reference |

#### Buttons (in incident cards)

- **✓ Acknowledge** — tags incident acknowledged
- **⚡ Escalate** — triggers PagerDuty + updates message
- **✓ Mark resolved** — marks incident resolved in DB
- **Approve / Reject** — on approval-pending action cards

**Local dev:** `ngrok http 8080` → use the `ngrok-free.app` URL in Slack settings.

---

## Web Policy Editor

**Location:** Settings → Policy & Actions tab

Edit `config/policy.yaml` and `config/actions.yaml` directly from the dashboard — no file system access needed.

#### Features

- **Live editor** — full textarea with monospace font, resizable
- **Save button** — enabled only when changes are pending; validates YAML before writing
- **Preview** (policy only) — parses the proposed policy and shows:
  - Auto-mitigate on/off
  - Max consecutive actions
  - Per-action approval status (auto / requires approval / disabled)
  - Live execution: which environments and actions are enabled
  - Escalation channels: which have live environments configured
- **Error display** — backend validation errors shown inline (e.g. invalid YAML syntax)

---

## Configuration Workflow

### Enable an Integration

1. Set up the external system (API key, webhook, etc.)
2. Add credentials to `.env`
3. Restart Heron: `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8080`
4. Test in dry-run: trigger a signal and check logs
5. Flip the policy gate in `config/policy.yaml`
6. Restart and test live

### Test Signal Trigger

```bash
curl -X POST http://localhost:8080/api/v1/sense/signals \
  -H "Content-Type: application/json" \
  -d '{
    "source": "test",
    "service": "test-service",
    "severity": "sev3",
    "message": "Integration test signal"
  }'
```

---

## Summary

| Integration | Type | File | Setup |
|---|---|---|---|
| Slack | Escalation | `app/integrations/slack.py` | 5 min |
| PagerDuty | Escalation | `app/integrations/pagerduty.py` | 10 min |
| Microsoft Teams | Escalation | `app/integrations/teams.py` | 5 min |
| OpsGenie | Escalation | `app/integrations/opsgenie.py` | 10 min |
| ArgoCD | Execution | `app/integrations/argocd.py` | 15 min |
| Flux CD | Execution | `app/integrations/flux.py` | 15 min |
| Prometheus | Ingestion | `app/services/pullers/prometheus_puller.py` | 5 min |
| CloudWatch | Ingestion | `app/services/pullers/cloudwatch_puller.py` | 5 min |
| Datadog | Ingestion | `app/services/pullers/datadog_puller.py` | 10 min |
| OTLP Ingest | Tracing | `app/api/routers/otlp.py` | 5 min |
| Jaeger | Tracing | `app/services/tracing/tracer.py` | 10 min |
| Zipkin | Tracing | `app/services/tracing/tracer.py` | 10 min |
| Tempo | Tracing | `app/services/tracing/tracer.py` | 10 min |
| Service Mesh | Tracing | `app/services/tracing/mesh.py` | 10 min |
| eBPF / Pixie | Tracing | `app/services/tracing/ebpf.py` | 30 min |
| OCI Discovery | Discovery | `app/services/discovery/oci/inventory.py` | 15 min |
| AWS Discovery | Discovery | `app/services/discovery/aws/inventory.py` | 10 min |
| GCP Discovery | Discovery | `app/services/discovery/gcp/inventory.py` | 15 min |
| Azure Discovery | Discovery | `app/services/discovery/azure/inventory.py` | 15 min |
| Kubernetes | Monitoring | `app/integrations/kubernetes.py` | 5 min |
| Jira | Ingestion | `app/integrations/jira.py` | 10 min |
| GitHub | Correlation | `app/api/routers/github.py` | 10 min |
| Claude / LLM | AI | `app/services/ai/` | 5 min |
| SLO Tracking | Analytics | `app/services/slo.py` | 0 min (auto-seeded) |
| Runbook Resolver | Knowledge | `app/services/runbook_resolver.py` | 5 min |
| Slack Bot | Interaction | `app/api/routers/slack_bot.py` | 15 min |
| Web Policy Editor | UI | `frontend/src/pages/Settings.tsx` | 0 min (built-in) |

---

**Questions?** Check individual source files or raise an issue at the project repo.
