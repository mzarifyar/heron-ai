# Heron — Integration Setup Guide

This document covers how to configure each live integration.
Credentials go in `.env` only — never committed to git.

---

## Slack

### What it does
Heron posts escalation messages to a Slack channel when an incident cannot
be auto-resolved and human intervention is required.

### Setup (one-time)

1. **Create a Slack App**
   - Go to [api.slack.com/apps](https://api.slack.com/apps)
   - Click **Create New App** → **From scratch**
   - Name it `Heron`, pick your workspace

2. **Enable Incoming Webhooks**
   - Go to **Incoming Webhooks** → toggle **On**
   - Click **Add New Webhook to Workspace**
   - Select the channel (e.g. `#incidents` or `#all-heron-notifications`)
   - Copy the webhook URL

3. **Add to `.env`**
   ```
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
   SLACK_DRY_RUN=false
   ```

4. **Regenerate the webhook if it was ever exposed publicly**
   - In your Slack App settings → Incoming Webhooks → Revoke and regenerate

### How it works
`app/integrations/slack.py` reads `SLACK_WEBHOOK_URL` and `SLACK_DRY_RUN`
from the environment. When `SLACK_DRY_RUN=false`, it POSTs a JSON payload
with mrkdwn-formatted blocks to the webhook URL.

### Testing
```bash
curl -s -X POST http://localhost:8080/api/v1/ops/escalate \
  -H "Content-Type: application/json" \
  -d '{
    "service": "payment-processor",
    "severity": "sev1",
    "summary": "Error rate spike — 8.3% exceeds threshold 5.0%",
    "environment": "prod",
    "region": "us-east-1",
    "actions_taken": ["pod_restart"],
    "incident_id": "test-001"
  }'
```

### Status
- ✅ Integrated and tested — message confirmed in `#all-heron-notifications`
- Integration name in Slack workspace: **Heron**

---

## PagerDuty

### What it does
Pages the on-call engineer via phone/SMS/mobile push when an incident
cannot be auto-resolved and Slack notification alone is insufficient.
Heron auto-resolves the PagerDuty alert when the incident is closed.

### Activation status
- ✅ **Code implemented** — `app/integrations/pagerduty.py`
- ⏸️ **Not wired** — Slack handles live escalations for now
- To activate: add `PAGERDUTY_ROUTING_KEY` to `.env` and set `PAGERDUTY_DRY_RUN=false`

### Setup (when ready)

1. **Get a PagerDuty account**
   - 14-day free trial at [pagerduty.com](https://www.pagerduty.com)
   - Or developer sandbox at [developer.pagerduty.com](https://developer.pagerduty.com)

2. **Create a Service**
   - Go to **Services** → **+ New Service**
   - Name it `Heron`
   - Under **Integrations**, choose **Events API v2**
   - Create the service
   - Copy the **Integration Key** (32-character hex string)

3. **Add to `.env`**
   ```
   PAGERDUTY_ROUTING_KEY=your-integration-key-here
   PAGERDUTY_DRY_RUN=false
   ```

### How it works
`app/integrations/pagerduty.py` sends a POST to
`https://events.pagerduty.com/v2/enqueue` with the routing key and
incident payload (severity, summary, service, region, Chronicle link).

### .env variables
```
PAGERDUTY_ROUTING_KEY=your-32-char-integration-key
PAGERDUTY_DRY_RUN=false
```

### How it works
`app/integrations/pagerduty.py` POSTs to `https://events.pagerduty.com/v2/enqueue`
using the Events API v2 payload format. Heron severity maps to PagerDuty severity:
`sev1→critical`, `sev2→error`, `sev3→warning`, `sev4→info`.
The `incident_id` is used as `dedup_key` so the same incident never pages twice.
`resolve_incident()` is called automatically when Heron closes the incident.

### Testing (once routing key is set)
```python
from app.integrations.pagerduty import trigger_incident
result = trigger_incident(
    target="prod",
    message="[TEST] Heron PagerDuty integration — please acknowledge and resolve",
    severity="sev2",
    service="payment-processor",
    region="us-east-1",
    dry_run=False,
)
print(result)
```

---

## OpsGenie

### What it does
Same role as PagerDuty — on-call alerting via phone/SMS/push. OpsGenie was
an Atlassian product. Direct signups were discontinued June 2025; access is
now via Jira Service Management (JSM) Premium.

### Activation status
- ✅ **Code implemented** — `app/integrations/opsgenie.py`
- ⏸️ **Not wired** — use Slack or PagerDuty instead for new deployments
- Kept for organisations that already have OpsGenie/JSM Premium access

### Setup (for existing OpsGenie/JSM accounts)

1. In OpsGenie or JSM: create an **API integration**, copy the API key
2. EU accounts: set `OPSGENIE_API_URL=https://api.eu.opsgenie.com/v2/alerts`

### .env variables
```
OPSGENIE_API_KEY=your-api-key
OPSGENIE_DRY_RUN=false
# OPSGENIE_API_URL=https://api.eu.opsgenie.com/v2/alerts   # EU only
```

### How it works
`app/integrations/opsgenie.py` POSTs to the OpsGenie Alerts API v2 with
`Authorization: GenieKey {key}`. Heron severity maps to OpsGenie priority:
`sev1→P1`, `sev2→P2`, `sev3→P3`, `sev4→P4`.
The `incident_id` is used as `alias` for deduplication and closure.
`close_alert()` is called automatically when Heron auto-resolves.

---

## Prometheus / Alertmanager

### What it does
Pulls firing alerts from Alertmanager and scrapes Golden Signal metrics
directly from Prometheus. Converts both into Heron signals that feed the
full autonomous loop — Sense → Insight → Claude Decide → Act → Verify.

This is the most common monitoring stack in the SRE world. Any team running
Prometheus already has Heron-ready signal data; this adapter unlocks it.

### Activation status
- ✅ **Code implemented** — `app/services/pullers/prometheus_puller.py`
- ✅ **Wired into scheduler** — activate by setting `enabled: true` in `config/pullers.yaml`
- ⏸️ **Disabled by default** — requires a running Prometheus/Alertmanager instance

### Setup

1. Add to `.env`:
```
PROMETHEUS_ALERTMANAGER_URL=http://alertmanager:9093    # for firing alerts
PROMETHEUS_URL=http://prometheus:9090                   # for metric scraping (optional)
PROMETHEUS_AUTH_TOKEN=Bearer xxxxx                      # if auth required (optional)
PROMETHEUS_BASIC_USER=user                              # basic auth alternative
PROMETHEUS_BASIC_PASS=pass
PROMETHEUS_INSECURE_TLS=false                           # set true to skip cert verify
PROMETHEUS_TIMEOUT_SECONDS=20
```

2. Enable in `config/pullers.yaml`:
```yaml
sources:
  prometheus:
    enabled: true
    interval_seconds: 30   # poll every 30 seconds
    batch_size: 500
```

3. Restart Heron. Firing Alertmanager alerts will appear in the Integrations → Alert Sources tab and flow into the autonomous loop immediately.

### What it collects

**From Alertmanager** (`/api/v2/alerts`):
- All active (not silenced/inhibited) alerts
- Alert labels mapped to service, region, environment
- Severity label mapped to Heron severity: `critical→sev1`, `warning→sev3`
- `alertname` normalised to snake_case metric name

**From Prometheus** (`/api/v1/query`) — optional, scraped every 30s:
- `error_rate` — HTTP 5xx / total request rate
- `latency_p99_ms` — p99 histogram quantile × 1000
- `cpu_utilization` — 1 − idle CPU rate
- `memory_utilization` — 1 − available/total memory

**Custom PromQL queries** — add any metric via env var:
```
PROMETHEUS_EXTRA_QUERIES=kafka_lag:kafka_consumer_group_lag:job,db_connections:pg_stat_activity_count:job
```
Format: `metric_name:promql:service_label`, comma-separated.

### How it works
`prometheus_puller.py` implements the `AlertSourceAdapter` interface.
The scheduler calls `pull()` every 30 seconds when enabled. Alerts are
grouped by service and ingested via `sense_service.ingest()` — the same
path as every other signal source. Dynamic baselines and anomaly detection
apply identically.

### Testing (once configured)
```bash
# Check if the puller is reachable
curl http://alertmanager:9093/api/v2/alerts

# Trigger a manual pull
curl -s -X POST http://localhost:8080/api/v1/pullers/run-now?source=prometheus | python3 -m json.tool
```

---

## Jira

### What it does
Heron ingests Jira incidents as signals and can create/update tickets
during the escalation flow.

### Setup
```
JIRA_BASE_URL=https://your-org.atlassian.net/rest/api/2
JIRA_BEARER_TOKEN=your-personal-access-token
JIRA_PROJECT_KEY=OPS
```

### Status
- ✅ Puller implemented — requires a real Jira instance to activate

---

## Environment Variable Reference

| Variable | Required | Description |
|---|---|---|
| `PROMETHEUS_ALERTMANAGER_URL` | For Prometheus alerts | Alertmanager base URL e.g. `http://alertmanager:9093` |
| `PROMETHEUS_URL` | For metric scraping | Prometheus base URL e.g. `http://prometheus:9090` |
| `PROMETHEUS_AUTH_TOKEN` | Optional | Bearer token for Prometheus/Alertmanager auth |
| `PROMETHEUS_BASIC_USER` | Optional | Basic auth username (alternative to token) |
| `PROMETHEUS_BASIC_PASS` | Optional | Basic auth password |
| `PROMETHEUS_INSECURE_TLS` | No (default: false) | Skip TLS certificate verification |
| `PROMETHEUS_EXTRA_QUERIES` | Optional | Additional PromQL: `name:query:label,...` |
| `SLACK_WEBHOOK_URL` | For live Slack | Incoming Webhook URL from api.slack.com |
| `SLACK_DRY_RUN` | No (default: true) | Set to `false` to send real messages |
| `PAGERDUTY_ROUTING_KEY` | For live PagerDuty | Events API v2 integration key |
| `PAGERDUTY_DRY_RUN` | No (default: true) | Set to `false` to fire real pages |
| `JIRA_BASE_URL` | For Jira | Your Jira REST API base URL |
| `JIRA_BEARER_TOKEN` | For Jira | Personal access token |
| `JIRA_PROJECT_KEY` | For Jira | Project key for new tickets |
| `CORTEX_DEMO_MODE` | No | Set to `true` for synthetic incidents |
| `DATABASE_URL` | No (default: SQLite) | PostgreSQL connection string for production |
