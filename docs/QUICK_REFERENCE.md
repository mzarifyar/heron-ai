# Heron Quick Reference

Fast lookup for environment variables, config snippets, and common commands.

**Last updated:** 2026-05-13

---

## Full Environment Variables Checklist

```bash
# ── Escalation: Slack ─────────────────────────────────────────────────────────
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
SLACK_DRY_RUN=true                     # flip to false for live messages

# ── Escalation: PagerDuty ─────────────────────────────────────────────────────
PAGERDUTY_ROUTING_KEY=your-32-char-key
PAGERDUTY_DRY_RUN=true                 # flip to false for live paging

# ── Escalation: Microsoft Teams ───────────────────────────────────────────────
TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
TEAMS_DRY_RUN=true                     # flip to false for live cards

# ── Escalation: OpsGenie ─────────────────────────────────────────────────────
OPSGENIE_API_KEY=your-api-key
OPSGENIE_DRY_RUN=true
# OPSGENIE_API_URL=https://api.eu.opsgenie.com/v2/alerts   # EU only

# ── Deployment: ArgoCD ───────────────────────────────────────────────────────
ARGOCD_SERVER_URL=https://argocd.example.com
ARGOCD_TOKEN=eyJhbGci...
ARGOCD_INSECURE=false                  # set true for self-signed certs
ARGOCD_DRY_RUN=true                    # flip to false for live rollbacks

# ── Deployment: Flux ─────────────────────────────────────────────────────────
FLUX_WEBHOOK_URL=http://flux-receiver.flux-system.svc/hook/heron
FLUX_WEBHOOK_TOKEN=your-token
FLUX_NAMESPACE=flux-system
FLUX_DRY_RUN=true                      # flip to false for live reconciles

# ── Alert Ingestion: Prometheus ───────────────────────────────────────────────
PROMETHEUS_ALERTMANAGER_URL=http://alertmanager:9093
PROMETHEUS_URL=http://prometheus:9090  # optional — enables metric scraping
PROMETHEUS_AUTH_TOKEN=Bearer-token    # optional
PROMETHEUS_TIMEOUT_SECONDS=20
PROMETHEUS_EXTRA_QUERIES=kafka_lag:kafka_consumer_group_lag:job  # custom PromQL

# ── Alert Ingestion: CloudWatch ───────────────────────────────────────────────
AWS_REGION=us-east-1
CLOUDWATCH_NAMESPACES=AWS/EC2,AWS/RDS,AWS/EKS  # optional namespace filter
# Credentials: instance profile (preferred on EC2) OR:
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

# ── Alert Ingestion: Datadog ──────────────────────────────────────────────────
DATADOG_API_KEY=dd-api-...
DATADOG_APP_KEY=dd-app-...
DATADOG_SITE=datadoghq.com             # or datadoghq.eu, us3.datadoghq.com

# ── Tracing: Jaeger / Zipkin / Tempo ─────────────────────────────────────────
JAEGER_URL=http://jaeger:16686
ZIPKIN_URL=http://zipkin:9411
TEMPO_URL=http://tempo:3200

# ── Tracing: eBPF / Pixie ────────────────────────────────────────────────────
PIXIE_API_KEY=px-api-...
PIXIE_CLUSTER_ID=...
# Without these, eBPF adapter runs demo data automatically

# ── Tracing: Service Mesh ────────────────────────────────────────────────────
MESH_PROMETHEUS_URL=http://prometheus:9090  # with Istio/Linkerd metrics
MESH_TYPE=auto                              # auto | istio | linkerd | cilium

# ── Discovery: OCI ───────────────────────────────────────────────────────────
OCI_TENANCY_OCID=ocid1.tenancy.oc1...
OCI_USER_OCID=ocid1.user.oc1...
OCI_FINGERPRINT=xx:xx:...
OCI_KEY_FILE=/path/to/key.pem
OCI_REGION=us-ashburn-1
OCI_COMPARTMENT_ID=ocid1.compartment.oc1...

# ── Discovery: AWS ───────────────────────────────────────────────────────────
AWS_ACCOUNT_ID=123456789012            # optional display label

# ── Discovery: GCP ───────────────────────────────────────────────────────────
GCP_PROJECT_ID=my-project-123
GCP_REGION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json  # or use `gcloud auth application-default login`

# ── Discovery: Azure ─────────────────────────────────────────────────────────
AZURE_SUBSCRIPTION_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_RESOURCE_GROUP=my-resource-group  # optional — scans all if unset
# Auth via: az login | AZURE_TENANT_ID + AZURE_CLIENT_ID + AZURE_CLIENT_SECRET

# ── Kubernetes ───────────────────────────────────────────────────────────────
HERON_KUBE_CLUSTER=my-cluster-name    # optional — for multi-cluster kubeconfig resolution

# ── Jira ─────────────────────────────────────────────────────────────────────
JIRA_BASE_URL=https://your-org.atlassian.net/rest/api/2
JIRA_BEARER_TOKEN=your-api-token
JIRA_PROJECT_KEY=OPS

# ── GitHub ───────────────────────────────────────────────────────────────────
GITHUB_WEBHOOK_SECRET=your-webhook-secret
GITHUB_DEFAULT_ENV=production

# ── AI / LLM ─────────────────────────────────────────────────────────────────
HERON_AI_PROVIDER=anthropic            # anthropic | openai | ollama
HERON_AI_API_KEY=sk-ant-...
HERON_AI_MODEL=claude-sonnet-4-6       # default for Anthropic
HERON_AI_BASE_URL=http://localhost:11434  # Ollama only
HERON_AI_MAX_TOKENS=1024               # overridden to 4096 for insight generation

# ── Runbook Resolver ─────────────────────────────────────────────────────────
RUNBOOK_DIR=docs/runbooks              # local markdown directory (default)
CONFLUENCE_BASE_URL=https://your-org.atlassian.net
CONFLUENCE_TOKEN=your-confluence-token
CONFLUENCE_SPACE=OPS                   # space key

# ── Slack Bot ────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...

# ── Waitlist (website) ───────────────────────────────────────────────────────
RESEND_API_KEY=re_...                  # confirmation emails via Resend
WAITLIST_FROM_EMAIL=Heron <hello@heron-ai.net>
WAITLIST_NOTIFY_EMAIL=you@yourcompany.com  # BCC on every submission
WAITLIST_STORE_PATH=data/waitlist.json     # local file store (dev only)
```

---

## Policy Configuration

### Escalation Channels

```yaml
# config/policy.yaml
escalation_channels:
  slack:
    live:
      local: false
      staging: false      # set true once SLACK_WEBHOOK_URL is configured
      prod: false
  pagerduty:
    live:
      local: false
      staging: false
      prod: false
  teams:
    live:
      local: false
      staging: false      # set true once TEAMS_WEBHOOK_URL is configured
      prod: false
```

### Live Execution (Reflex)

```yaml
live_execution:
  enabled: true                      # global kill switch
  environments:
    local: false
    staging: true
    prod: false
  per_action:
    observe_only: false
    restart_component: true
    rollback_latest_deployment: false  # high-risk: keep false until confident
    escalate_incident: true
    page_on_call: true
    argocd_rollback: false             # enable once ArgoCD is configured
    argocd_sync: false
    flux_reconcile: false
```

---

## Alert Pullers (config/pullers.yaml)

```yaml
scheduler:
  enabled: true
sources:
  jira:
    enabled: true
    interval_seconds: 60
  prometheus:
    enabled: false        # set true + PROMETHEUS_ALERTMANAGER_URL
    interval_seconds: 30
  cloudwatch:
    enabled: false        # set true + AWS credentials
    interval_seconds: 60
  datadog:
    enabled: false        # set true + DATADOG_API_KEY + DATADOG_APP_KEY
    interval_seconds: 60
  tracing:
    enabled: false        # set true + any of JAEGER_URL / PIXIE_API_KEY / MESH_PROMETHEUS_URL
    interval_seconds: 30
```

---

## Quick Setup: Slack (5 min)

```bash
# 1. api.slack.com/apps → Incoming Webhooks → Add → copy URL
# 2. Add to .env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_DRY_RUN=true

# 3. Restart backend
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8080

# 4. Trigger test signal
curl -X POST http://localhost:8080/api/v1/sense/signals \
  -H "Content-Type: application/json" \
  -d '{"source":"test","service":"test-service","severity":"sev3","message":"Slack test"}'

# 5. Check logs — should show "dry_run" status
# 6. Set escalation_channels.slack.live.staging: true in policy.yaml
# 7. Restart + test live
```

---

## Quick Setup: PagerDuty (10 min)

```bash
# 1. PagerDuty → Services → Integrations → Events API v2 → copy routing key
PAGERDUTY_ROUTING_KEY=your-32-char-key
PAGERDUTY_DRY_RUN=true

# 2. Restart → test (same as Slack)
# 3. Set escalation_channels.pagerduty.live.staging: true
# 4. Restart → test live
```

---

## Quick Setup: CloudWatch (5 min)

```bash
# On EC2: no credentials needed — instance profile auto-discovered
# Outside AWS:
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# Enable in pullers.yaml:
# sources.cloudwatch.enabled: true

# Restart → CloudWatch alarms in ALARM state will appear as signals
```

---

## Quick Setup: Datadog (10 min)

```bash
DATADOG_API_KEY=dd-api-...
DATADOG_APP_KEY=dd-app-...
DATADOG_SITE=datadoghq.com

# Enable in pullers.yaml:
# sources.datadog.enabled: true

# Restart → firing monitors appear as signals
```

---

## Quick Setup: ArgoCD (15 min)

```bash
# 1. ArgoCD UI → Settings → Accounts → Generate Token
ARGOCD_SERVER_URL=https://argocd.example.com
ARGOCD_TOKEN=eyJhbGci...
ARGOCD_DRY_RUN=true

# 2. Label your apps in Git:
#    metadata.labels.heron-service: payments-api

# 3. Enable in policy.yaml:
#    live_execution.per_action.argocd_rollback: true

# 4. Restart → test → flip ARGOCD_DRY_RUN=false when confident
```

---

## Quick Setup: AI / LLM (5 min)

```bash
# Get API key from console.anthropic.com
HERON_AI_PROVIDER=anthropic
HERON_AI_API_KEY=sk-ant-...

# Restart → every incident now gets LLM-powered action selection
# Dashboard → Intelligence → Generate Insights → AI analysis of Chronicle history
```

---

## Quick Setup: Runbook Resolver (5 min)

```bash
# 1. Create docs/runbooks/ directory
mkdir -p docs/runbooks

# 2. Add markdown runbooks (filename hints Heron to the service):
#    docs/runbooks/payment-processor-connection-pool.md

# 3. Index via API:
curl -X POST http://localhost:8080/api/v1/runbooks/index

# 4. Or click "Re-index" in the SLO & Runbooks dashboard page
# 5. New incidents will now get runbook.matched timeline entries
```

---

## Common Patterns

### All integrations default to dry-run

Every integration defaults to logging-only. You must explicitly flip:
- `*_DRY_RUN=false` in `.env` (integration level)
- `escalation_channels.<ch>.live.<env>: true` in `policy.yaml` (service level)

Both gates must be open for a live notification to fire.

### Test any signal pipeline

```bash
curl -X POST http://localhost:8080/api/v1/sense/signals \
  -H "Content-Type: application/json" \
  -d '{"source":"test","service":"payment-processor","severity":"sev2","message":"test"}'

# Then check logs for the full loop:
# Sense → Insight → Decide (LLM or rules) → Act (dry_run) → Verify → Learn
```

### Discovery without credentials (demo mode)

Every cloud scanner has a demo fallback. Click "Use demo data" in the Discovery page — no credentials needed — to see the full coverage map UI with 12 realistic resources across compute, database, kubernetes, and load balancer types.

### Enable SLO tracking

SLOs are auto-seeded on the first visit to `/slo`. Burn rates are computed from Signal data — the more signals flowing, the more accurate the burn rate. With no signals, budget shows 100% consumed as a conservative worst-case.

---

## File Locations

| Item | Path |
|---|---|
| Environment variables | `.env` |
| Policy configuration | `config/policy.yaml` |
| Action definitions | `config/actions.yaml` |
| Puller configuration | `config/pullers.yaml` |
| Discovery catalog | `config/discovery/catalog/*.yaml` |
| Customer discovery overrides | `config/discovery/customer/discovery.yaml` |
| Anomaly thresholds | `config/thresholds.json` |
| Cluster targets | `config/cluster_targets.json` |
| Local database | `data/cortex_local.db` |
| Jira auth cache | `data/jira_auth.json` |
| Local runbooks | `docs/runbooks/*.md` |
| API documentation | `http://localhost:8080/docs` |

## Dashboard Pages

| Page | URL | Purpose |
|---|---|---|
| Dashboard | `/dashboard` | Active incidents, learn summary, cluster health |
| Golden Signals | `/golden-signals` | Per-service latency, traffic, errors, saturation |
| Incidents | `/incidents` | Chronicle — full incident history |
| Intelligence | `/intelligence` | AI recommendations, near-misses, Learn loop |
| Service Map | `/service-map` | Live topology, traffic animation, edge latency |
| SLO & Runbooks | `/slo` | Error budget tracking + runbook index |
| Discovery | `/discovery` | Cloud infrastructure scan + coverage map |
| Infrastructure | `/infrastructure` | Cluster hygiene |
| Integrations | `/integrations` | Connected sources status |
| Settings | `/settings` | Policy editor, thresholds, env info |

## API Endpoints (Key)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/sense/signals` | Ingest a signal |
| `GET /api/v1/dashboard/intelligence/generate` | Trigger AI insight generation (POST) |
| `GET /api/v1/slo/burn` | All SLO burn rates |
| `GET /api/v1/tracing/graph` | Live service dependency graph |
| `GET /api/v1/tracing/dependencies/{service}` | Upstream/downstream for a service |
| `POST /api/v1/discovery/connect` | Start infrastructure scan |
| `GET /api/v1/discovery/report` | Coverage map from last scan |
| `POST /api/v1/runbooks/index` | Re-index runbooks |
| `POST /slack/commands` | Slack slash command receiver |
| `POST /slack/interactive` | Slack button click receiver |
| `POST /otlp/v1/traces` | OTLP trace ingest |
| `POST /otlp/v1/metrics` | OTLP metric ingest |
| `POST /webhooks/github` | GitHub deployment webhook |
| `POST /api/v1/ops/config/policy/preview` | Preview policy changes |
| `GET /api/v1/ops/config/{name}` | Read config file |
| `PUT /api/v1/ops/config/{name}` | Write config file |

---

## Troubleshooting Checklist

```bash
# 1. Check env vars are set
grep -E "SLACK|PAGERDUTY|ARGOCD|HERON_AI" .env

# 2. Check service health
curl http://localhost:8080/api/v1/health

# 3. Check logs for the integration name
grep -i "slack\|pagerduty\|argocd\|datadog" uvicorn.log

# 4. Check policy gates (all false = safe default)
grep -A 15 "escalation_channels" config/policy.yaml

# 5. Verify dry-run status
grep DRY_RUN .env

# 6. Trigger a test signal and watch the full loop
curl -X POST http://localhost:8080/api/v1/sense/signals \
  -H "Content-Type: application/json" \
  -d '{"source":"test","service":"test-svc","severity":"sev3","message":"test"}'

# 7. View API docs (FastAPI auto-generated)
open http://localhost:8080/docs
```

---

**Last updated:** 2026-05-13
