# Integration Decision Tree

Quick guide to choosing the right integration for your use case.

**Last updated:** 2026-05-13

---

## "I need to notify my team when an incident happens"

### What's your communication platform?

- **Slack** → [Slack Integration](#slack)
- **Microsoft Teams** → [Teams Integration](#teams)
- **PagerDuty for on-call** → [PagerDuty Integration](#pagerduty)
- **OpsGenie** → [OpsGenie Integration](#opsgenie)

### Slack
- **Best for:** General team notifications, incident cards with action buttons
- **Risk:** Low — notifications only
- **Setup time:** 5 minutes
- **Dry-run:** `SLACK_DRY_RUN=true` (default)
- **Bottleneck:** Incoming Webhook URL from Slack app

**Next step:** `QUICK_REFERENCE.md` → "Quick Setup: Slack"

### Teams
- **Best for:** Enterprise Microsoft environments, Adaptive Cards, rich formatting
- **Risk:** Low — notifications only
- **Setup time:** 5 minutes
- **Dry-run:** `TEAMS_DRY_RUN=true` (default)
- **Bottleneck:** Incoming Webhook URL from Teams channel connector

**Next step:** Set `TEAMS_WEBHOOK_URL` in `.env` + flip policy gate

### PagerDuty
- **Best for:** On-call paging, escalation policies, alert deduplication
- **Risk:** Medium — pages your on-call team
- **Setup time:** 10 minutes
- **Dry-run:** `PAGERDUTY_DRY_RUN=true` (default)
- **Bottleneck:** 32-char routing key from Events API v2 integration

**Next step:** `QUICK_REFERENCE.md` → "Quick Setup: PagerDuty"

### OpsGenie
- **Best for:** Alert aggregation, team rotations (existing OpsGenie accounts only)
- **Risk:** Medium — creates visible alerts
- **Setup time:** 10 minutes
- **Dry-run:** `OPSGENIE_DRY_RUN=true` (default)
- **Bottleneck:** API key from OpsGenie/JSM settings

---

## "I need Heron to automatically fix things"

### What kind of fixes?

- **Restart failed pods** → [Kubernetes + Reflex](#kubernetes)
- **Rollback a bad GitOps deployment** → [ArgoCD](#argocd) or [Flux CD](#flux-cd)
- **Sync Git to live state** → [ArgoCD](#argocd) or [Flux CD](#flux-cd)

### Kubernetes
- **Best for:** Direct kubectl commands, pod restarts, rollouts
- **Risk:** Medium-High — can restart/delete production workloads
- **Setup time:** 5 minutes (kubeconfig)
- **Dry-run:** Reflex dry-run mode in `config/policy.yaml`
- **Bottleneck:** Kubeconfig access to the target cluster

**Next step:** Set `HERON_KUBE_CLUSTER` if multi-cluster; ensure kubeconfig in `~/.kube/config`

### ArgoCD
- **Best for:** GitOps deployments — rollback to previous revision, sync with Git
- **Risk:** High — can roll back production
- **Setup time:** 15 minutes
- **Dry-run:** `ARGOCD_DRY_RUN=true` (default)
- **Bottleneck:** API token + labelling apps with `heron-service`

**Steps:**
1. `ARGOCD_SERVER_URL` + `ARGOCD_TOKEN` in `.env`
2. Label apps: `metadata.labels.heron-service: my-service`
3. Enable in policy: `live_execution.per_action.argocd_rollback: true`
4. Keep `ARGOCD_DRY_RUN=true` until confident

### Flux CD
- **Best for:** Flux GitOps — trigger reconciliation, suspend to pause auto-sync
- **Risk:** High — immediate reconciliations can affect production
- **Setup time:** 15 minutes
- **Dry-run:** `FLUX_DRY_RUN=true` (default)
- **Bottleneck:** Flux Receiver webhook setup in cluster

**Tip:** Use `flux://suspend/{service}` to stop Flux overwriting a Heron fix mid-incident.

---

## "I need to pull alerts into Heron"

### Where are your alerts coming from?

- **Prometheus / Alertmanager** → [Prometheus](#prometheus)
- **AWS CloudWatch** → [CloudWatch](#cloudwatch)
- **Datadog** → [Datadog](#datadog)
- **Jira tickets** → [Jira](#jira)
- **Kubernetes pod failures** → [Kubernetes monitoring](#kubernetes-monitoring)

### Prometheus
- **Best for:** Alertmanager firing alerts + PromQL metric scraping
- **Risk:** Low — read-only
- **Setup time:** 5 minutes
- **Bottleneck:** Alertmanager URL

**Steps:** `PROMETHEUS_ALERTMANAGER_URL` in `.env` → `prometheus.enabled: true` in `pullers.yaml`

### CloudWatch
- **Best for:** AWS-native teams — EC2, RDS, EKS, Lambda alarms + AWS Health events
- **Risk:** Low — read-only
- **Setup time:** 5 minutes (instance profile auto-discovered on EC2)
- **Bottleneck:** On EC2: nothing. Off EC2: `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`

**Steps:** Optionally set `AWS_REGION` + `CLOUDWATCH_NAMESPACES` → `cloudwatch.enabled: true` in `pullers.yaml`

### Datadog
- **Best for:** Teams already running Datadog — import firing monitors and alert events
- **Risk:** Low — read-only
- **Setup time:** 10 minutes
- **Bottleneck:** Both `DATADOG_API_KEY` and `DATADOG_APP_KEY` required

**Steps:** Set both keys + `DATADOG_SITE` → `datadog.enabled: true` in `pullers.yaml`

### Jira
- **Best for:** Ticket-based incidents, Service Desk, manual escalation tracking
- **Risk:** Low — read-only ingestion, write for escalation tickets
- **Setup time:** 10 minutes
- **Bottleneck:** API token + JQL queries in `config/jira_queries.json`

### Kubernetes Monitoring
- **Best for:** Pod crashes, OOMKills, node issues surfaced automatically
- **Risk:** Low — read-only
- **Setup time:** 5 minutes
- **Bottleneck:** Kubeconfig + `config/cluster_targets.json`

---

## "I need distributed tracing / service topology"

### What do you already have?

- **Jaeger, Zipkin, or Tempo** → [Tracing Connectors](#tracing-connectors)
- **Istio, Linkerd, or Cilium** → [Service Mesh](#service-mesh)
- **Nothing yet, want zero-code** → [OTLP Ingest](#otlp-ingest) or [eBPF / Pixie](#ebpf--pixie)

### Tracing Connectors
Heron polls your existing tracing system and builds service edge metrics automatically.

- `JAEGER_URL=http://jaeger:16686`
- `ZIPKIN_URL=http://zipkin:9411`
- `TEMPO_URL=http://tempo:3200`

Set whichever applies → `tracing.enabled: true` in `pullers.yaml` → service map populates.

### Service Mesh
If you have Istio, Linkerd, or Cilium with Prometheus scraping:

- `MESH_PROMETHEUS_URL=http://prometheus:9090`
- `MESH_TYPE=auto` (auto-detects)

### OTLP Ingest
Point any OTel-instrumented app directly at Heron:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://your-heron-host
OTEL_EXPORTER_OTLP_PROTOCOL=http/json
```

No separate collector needed. Traces → service edge latency. Metrics → Signal pipeline.

### eBPF / Pixie
Zero code changes, captures all HTTP/gRPC/DB traffic at the kernel level:

```bash
PIXIE_API_KEY=px-api-...
PIXIE_CLUSTER_ID=...
```

**Without credentials:** Demo mode runs automatically — 10 realistic edges keep the service map populated at all times.

---

## "I want to discover what infrastructure I have"

### Which cloud?

- **Oracle Cloud (OCI)** → Discovery page → select OCI + `OCI_COMPARTMENT_ID`
- **AWS** → Discovery page → select AWS (auto-discovers credentials)
- **Google Cloud** → Discovery page → select GCP + `GCP_PROJECT_ID`
- **Azure** → Discovery page → select Azure + `AZURE_SUBSCRIPTION_ID`

All clouds:
- Fall back to a 12-resource demo scan when credentials aren't configured
- Check the "Use demo data" checkbox to always see the coverage map
- Produce the same coverage map UI: 🟢 Monitored / 🟡 Partial / 🔴 Unmonitored / ⚪ Unknown
- Support click-to-filter by status and resource type
- Selective activation: check individual resources before enabling monitoring

**No credentials? Use demo mode** — the UI is fully functional with simulated data.

---

## "I want AI-powered incident decisions"

### LLM Decide Step

Every incident automatically gets LLM-powered action selection when `HERON_AI_PROVIDER` is set:

```bash
HERON_AI_PROVIDER=anthropic
HERON_AI_API_KEY=sk-ant-...
```

Claude Sonnet 4.6 reasons over signal context, Chronicle history (90d), action confidence scores, and service dependency graph. Falls back to rule-based engine if unavailable.

### AI Intelligence Insights

On-demand analysis of all Chronicle data:
- Dashboard → Intelligence tab → "Generate Insights" button
- Or: `POST /api/v1/dashboard/intelligence/generate`
- Rate-limited to once per hour
- Returns recommendations, risks, and cross-service patterns

---

## "I want SLO tracking and error budgets"

→ Dashboard → **SLO & Runbooks** page (`/slo`)

8 default SLOs are auto-seeded on first visit (api-gateway 99.9%, payment-processor 99.95%, etc.). Add custom SLOs from the UI — no YAML needed.

**Burn rate interpretation:**
- 1× = nominal (budget lasts exactly the window)
- 5× = budget exhausted in 1/5 of window (6 days on a 30d SLO)
- Alert fires when budget remaining ≤ 10% (configurable)

---

## "I want runbooks surfaced automatically during incidents"

→ Create `docs/runbooks/*.md` → `POST /api/v1/runbooks/index` (or click Re-index in UI)

Heron matches runbooks to incidents by keyword overlap (service name, metric name, incident summary). When a new incident opens in Chronicle, a `runbook.matched` timeline entry appears with the top 3 matches and their URLs.

**Confluence:** Set `CONFLUENCE_BASE_URL` + `CONFLUENCE_TOKEN` + `CONFLUENCE_SPACE` — Heron imports pages with "runbook/playbook/sop" in the title.

---

## "I want to interact with Heron from Slack"

→ [Slack Bot](#slack-bot-setup)

### Slack Bot Setup
1. Existing or new Slack app at [api.slack.com/apps](https://api.slack.com/apps)
2. Slash Commands → `/heron` → `https://your-host/slack/commands`
3. Interactivity → `https://your-host/slack/interactive`
4. Bot scopes: `commands`, `chat:write`, `chat:write.public` → Install → copy token
5. `SLACK_BOT_TOKEN=xoxb-...` + `SLACK_SIGNING_SECRET=...` in `.env`

**Local dev:** `ngrok http 8080` → use the ngrok URL in Slack settings.

---

## "I want to edit policy without touching YAML files"

→ Dashboard → **Settings** → **Policy & Actions** tab

Full editor for `config/policy.yaml` and `config/actions.yaml` with:
- Save button (validates before writing)
- Preview button (policy only) — shows which actions would auto-approve vs require human approval before saving

---

## Step-by-Step Rollout

### Phase 1 — Observation (start here)
Get incidents into Heron from your existing systems.

| Step | Integration | Time |
|---|---|---|
| 1 | Prometheus or CloudWatch or Datadog | 5-10 min |
| 2 | GitHub webhook (deploy correlation) | 10 min |
| 3 | Jira (if ticket-based) | 10 min |
| 4 | OTLP or tracing connector | 5-15 min |

**Result:** Chronicle fills with real incidents. Service map shows live topology.

### Phase 2 — Notification
Let Heron tell your team what it's seeing.

| Step | Integration | Time |
|---|---|---|
| 1 | Slack notifications (dry-run first) | 5 min |
| 2 | PagerDuty for sev1/sev2 (dry-run first) | 10 min |
| 3 | Slack Bot `/heron status` | 15 min |

**Important:** Stay in dry-run mode and monitor logs for 1-2 days before enabling live.

### Phase 3 — AI Intelligence
Let Claude reason over your incident history.

| Step | Action | Time |
|---|---|---|
| 1 | Set `HERON_AI_PROVIDER=anthropic` + API key | 5 min |
| 2 | Visit Intelligence page → Generate Insights | immediate |
| 3 | Review recommendations | ongoing |

### Phase 4 — Action (autonomous remediation)
Let Heron fix simple issues automatically.

| Step | Integration | Risk | Time |
|---|---|---|---|
| 1 | Enable Reflex dry-run for restart_component | Low | 0 min |
| 2 | Watch dry-run logs for 1 week | — | — |
| 3 | Enable live restart_component in staging | Medium | 5 min |
| 4 | ArgoCD rollback for post-deploy incidents | High | 15 min |

**Never skip dry-run.** Monitor closely before enabling in prod.

### Phase 5 — SLO + Runbooks
Complete observability.

| Step | Action |
|---|---|
| 1 | Visit `/slo` — SLOs auto-seeded |
| 2 | Add runbooks to `docs/runbooks/` and index |
| 3 | Review runbook matches in Chronicle timelines |

---

## Risk Matrix

| Integration | Ingestion | Notification | Remediation | Risk |
|---|---|---|---|---|
| Slack (webhook) | — | ✓ | — | Low |
| PagerDuty | — | ✓ | — | Low-Medium |
| Microsoft Teams | — | ✓ | — | Low |
| OpsGenie | — | ✓ | — | Low-Medium |
| CloudWatch | ✓ | — | — | Low |
| Datadog | ✓ | — | — | Low |
| Prometheus | ✓ | — | — | Low |
| GitHub | ✓ | — | — | Low |
| OTLP Ingest | ✓ | — | — | Low |
| Jaeger/Zipkin/Tempo | ✓ | — | — | Low |
| Service Mesh | ✓ | — | — | Low |
| eBPF / Pixie | ✓ | — | — | Low |
| Jira | ✓ | ✓ | — | Low |
| Kubernetes | ✓ | — | ✓ | Medium-High |
| ArgoCD | — | — | ✓ | High |
| Flux CD | — | — | ✓ | High |
| Slack Bot | — | ✓ | ✓ (approve) | Low-Medium |
| AI / LLM | — | — | ✓ (decide) | Medium |

---

## Not Sure Where to Start?

1. **Lowest risk + highest value:** Enable Prometheus or CloudWatch (read-only ingestion)
2. **See the service map immediately:** eBPF demo mode is on by default — visit `/service-map`
3. **See AI in action:** Set `HERON_AI_PROVIDER=anthropic` + key → every incident gets LLM reasoning
4. **Check SLOs immediately:** Visit `/slo` — 8 default SLOs auto-seeded, budget computed from signals

**Golden path for first 30 minutes:**
1. Set `HERON_AI_PROVIDER` + key
2. Enable one alert source (Prometheus or CloudWatch)
3. Trigger a test signal via curl
4. Watch the full loop in logs: Sense → LLM Decide → dry-run Act → Verify → Learn
5. Check Intelligence page for recommendations

---

**Full setup details:** `docs/IMPLEMENTATIONS_GUIDE.md`  
**Env var reference:** `docs/QUICK_REFERENCE.md`
