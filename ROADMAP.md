# Heron — Roadmap & Future Work

## Cloud Provider Strategy

Heron targets the four major cloud providers. Development happens one at a time — prove it solid on each before moving to the next.

---

### The Progression

| Phase | Cloud | Why this order |
|---|---|---|
| **Phase 1** | Oracle Cloud (OCI) | Best free tier (4 ARM cores, 24GB RAM, never expires). Validate the full stack with zero cost. |
| **Phase 2** | AWS | Largest market share (~32%). Most SRE teams live here. EKS, CloudWatch, IAM are industry standards. |
| **Phase 3** | GCP | Fast-growing in AI/ML teams. GKE is the cleanest Kubernetes experience. Natural fit for the AI layer. |
| **Phase 4** | Azure | Enterprise and Microsoft-shop focus. AKS, Azure Monitor, Managed Identities. |

---

### Definition of "Solid on a Cloud"

Before moving to the next cloud, Heron must pass all five checks on the current one:

1. ✅ **Deploys and runs** — one-command setup, Heron starts cleanly on that cloud's compute
2. ✅ **Native alert source** — pulling real alerts from that cloud's monitoring system (CloudWatch, OCI Monitoring, GCP Cloud Monitoring, Azure Monitor)
3. ✅ **Kubernetes integration** — cluster hygiene working against that cloud's K8s flavor (OKE, EKS, GKE, AKS)
4. ✅ **Native auth** — using that cloud's IAM model, not static credentials (Instance Principals, IAM roles, Service Accounts, Managed Identities)
5. ✅ **Documented setup** — a runbook that takes a fresh cloud account to a running Heron instance in under 30 minutes

---

### Phase 1 — Oracle Cloud (OCI)

**Compute:** Ampere A1 — 4 ARM cores, 24GB RAM, always free. Enough to run the full stack.  
**Database:** Oracle Autonomous DB (2 × 20GB, always free) or PostgreSQL on the VM.  
**Kubernetes:** OKE (Oracle Container Engine) or k3s on the free VMs.  
**Monitoring:** OCI Monitoring — metrics, alarms, and OCI Health Events API.  
**Auth:** OCI IAM with Instance Principals — no static keys needed on the VM.

**What to build for OCI:**
- `app/cloud/oci/alert_puller.py` — poll OCI Monitoring alarms via OCI SDK
- `app/cloud/oci/auth.py` — Instance Principal authentication (auto-rotates, no keys)
- `app/cloud/oci/kubernetes.py` — OKE cluster discovery and kubeconfig resolution
- `scripts/deploy_oci.sh` — one-command deploy script
- `docs/setup-oci.md` — 30-minute setup guide

**ARM note:** Python + FastAPI + SQLAlchemy all run natively on ARM. The Ampere A1 is fast. Test all dependencies compile cleanly on `aarch64` before considering this phase done.

---

### Phase 2 — AWS

**Compute:** EC2 t3.micro (1 vCPU, 1GB RAM) — free for 12 months. Beyond the trial: t4g.small spot instances are ~$3/month.  
**Database:** RDS PostgreSQL t3.micro — free for 12 months. Beyond: use SQLite on EC2 or a small RDS.  
**Kubernetes:** EKS (not free — $0.10/hr cluster fee). For testing: k3s on EC2 at no extra cost.  
**Monitoring:** CloudWatch Alarms and AWS Health API — most common alerting stack in SRE.  
**Auth:** IAM roles attached to EC2 instances — no static `AWS_ACCESS_KEY_ID` in env files.

**What to build for AWS:**
- `app/cloud/aws/alert_puller.py` — poll CloudWatch Alarms via boto3 (`describe_alarms_for_metric`)
- `app/cloud/aws/health_puller.py` — poll AWS Health API for service events
- `app/cloud/aws/auth.py` — EC2 instance profile credential resolution (boto3 handles this natively)
- `app/cloud/aws/kubernetes.py` — EKS cluster discovery and kubeconfig via `aws eks update-kubeconfig`
- `scripts/deploy_aws.sh` — one-command deploy script (EC2 + security group + IAM role)
- `docs/setup-aws.md` — 30-minute setup guide

**Market note:** AWS is where the Prometheus and CloudWatch adapters matter most. Most AWS-native SRE teams use CloudWatch for alarms and EKS for workloads. Getting Heron solid on AWS is the unlock for the largest customer segment.

---

### Phase 3 — GCP

**Compute:** e2-micro (0.25 vCPU, 1GB RAM) — always free but small. For real testing: e2-small (~$13/month).  
**Database:** No always-free managed DB. Use Cloud SQL PostgreSQL (f1-micro, cheapest tier) or SQLite on the VM.  
**Kubernetes:** GKE Autopilot — cluster management fee waived for one Autopilot cluster. Pay only for node compute when pods are running.  
**Monitoring:** Cloud Monitoring (formerly Stackdriver) — metrics, alerts, uptime checks.  
**Auth:** Service Accounts with Workload Identity Federation — the GCP-native way.

**What to build for GCP:**
- `app/cloud/gcp/alert_puller.py` — poll Cloud Monitoring alerting policies via Google Cloud Python SDK
- `app/cloud/gcp/auth.py` — Application Default Credentials (ADC) + service account key resolution
- `app/cloud/gcp/kubernetes.py` — GKE cluster discovery via `gcloud container clusters list` and kubeconfig generation
- `scripts/deploy_gcp.sh` — one-command deploy script
- `docs/setup-gcp.md` — 30-minute setup guide

**AI layer note:** GCP is the natural home for the LLM-powered Decide and Intelligence features. Vertex AI runs Gemini natively. When the AI provider abstraction (`app/services/ai/provider.py`) is built, add a GCP/Vertex AI backend. This makes GCP the showcase cloud for Heron's intelligence features.

---

### Phase 4 — Azure

**Compute:** B1s VM (1 vCPU, 1GB RAM) — free for 12 months. Beyond: B2s (~$35/month) or spot VMs.  
**Database:** No always-free tier. Azure Database for PostgreSQL Flexible Server (cheapest: ~$12/month) or SQLite on the VM.  
**Kubernetes:** AKS — cluster management is free, pay only for worker node VMs.  
**Monitoring:** Azure Monitor — metrics, alerts, Log Analytics, Application Insights.  
**Auth:** Managed Identities — Azure equivalent of IAM roles. No credentials stored anywhere.

**What to build for Azure:**
- `app/cloud/azure/alert_puller.py` — poll Azure Monitor alerts via Azure SDK for Python (`azure-mgmt-monitor`)
- `app/cloud/azure/auth.py` — DefaultAzureCredential (handles Managed Identity, CLI, env vars automatically)
- `app/cloud/azure/kubernetes.py` — AKS cluster discovery and kubeconfig via `az aks get-credentials`
- `scripts/deploy_azure.sh` — one-command deploy using Azure CLI
- `docs/setup-azure.md` — 30-minute setup guide

**Enterprise note:** Azure is the Microsoft-shop cloud. Teams running .NET, Azure DevOps, and Teams are here. When building Azure support, prioritise the Teams integration (as an Escalate channel alongside Slack) — it's the communication tool for every Azure-native team.

---

### Shared Cloud Architecture

Each cloud implementation follows the same pattern. All live under `app/cloud/`:

```
app/cloud/
├── base.py              ← CloudAdapter abstract interface
├── oci/
│   ├── alert_puller.py
│   ├── auth.py
│   └── kubernetes.py
├── aws/
│   ├── alert_puller.py
│   ├── health_puller.py
│   ├── auth.py
│   └── kubernetes.py
├── gcp/
│   ├── alert_puller.py
│   ├── auth.py
│   └── kubernetes.py
└── azure/
    ├── alert_puller.py
    ├── auth.py
    └── kubernetes.py
```

The `base.py` interface defines what every cloud adapter must implement:
```python
class CloudAdapter(ABC):
    def get_alerts(self) -> list[SignalPayload]: ...
    def get_clusters(self) -> list[ClusterInfo]: ...
    def get_credentials(self) -> CloudCredentials: ...
```

This means the scheduler, the signal pipeline, and the cluster hygiene puller never need to know which cloud they're running on. You configure `HERON_CLOUD_PROVIDER=aws` and the right adapter loads.

---

> Last updated: May 2026  
> This document tracks what's built, what needs wiring, and what's next.

---

## The Closed Loop — Honest Audit

The website describes a 7-step autonomous loop. Below is the exact state of each step — what the website claims, what is actually implemented, what the gap is, and what it would take to close it.

---

### Step 1 — Observe
**File:** `app/services/sense.py` (142 lines)  
**Website claim:** *"Every signal ingested and normalised in real time"*  
**Verdict:** ✅ Accurate

**What's built:**
Signal ingestion is fully implemented. `SenseService` accepts signals via `POST /api/v1/sense/signals`, validates them against the schema, runs them through the alarm guard (which can drop low-confidence signals based on configurable rules), and buffers them in memory for the Insight step. Supports three signal types: `metric`, `event`, and `log`. The context model carries service, tier, environment, region, component, and labels. An `org_id` field is already in place for future multi-tenancy.

The alarm guard checks a configurable script (`tools/get_alarm_status.py`) before accepting a signal — this is the noise filter. Signals that don't pass the guard are dropped and logged. Accepted signals are passed downstream to Insight immediately.

**Gaps:** None in the core path. The signal schema is generic enough to accept from any source. The buffer is in-memory and resets on restart — a persistent signal queue (Redis, Kafka) would be needed for production-grade durability.

---

### Step 2 — Detect
**File:** `app/services/insight.py` (148 lines)  
**Website claim:** *"Anomalies surfaced, alert noise filtered"*  
**Verdict:** ⚠️ Partially accurate — detection works but is simpler than implied

**What's built:**
`InsightService` loads threshold configurations from `config/thresholds.json` and evaluates each incoming signal against warn/critical thresholds for its metric name and service. If a metric value crosses a threshold, an `Anomaly` object is created and passed to Core. The anomaly carries severity (info/sev3/sev2/sev1), the observed value, the threshold breached, and the signal context.

This is static threshold detection — it works and it is used in production-grade systems (Nagios, basic PagerDuty rules). For a first version it is entirely valid.

**The gap:**
The website implies intelligent anomaly detection. What exists is an if/else check on numbers. There is no:
- **Cross-signal correlation** — two related services degrading together looks the same as one
- **Baseline learning** — the threshold is a static config file, not learned from traffic patterns
- **Seasonality awareness** — 80% CPU at 3 PM on a Tuesday vs 80% CPU at 3 AM on a Sunday are treated identically
- **Rate-of-change detection** — a metric spiking from 10% to 90% in 30 seconds vs drifting there over 3 hours look the same

**To close the gap:**
- Replace static thresholds with dynamic baselines computed from rolling signal history (e.g., 3-sigma from a 7-day window)
- Add cross-signal correlation: if `error_rate` and `latency_p99` both spike within 60 seconds on the same service, that's a stronger signal
- Consider integrating an ML anomaly model (Isolation Forest, Prophet for seasonal baselines) as an optional second layer alongside the static thresholds

---

### Step 3 — Decide
**File:** `app/services/core.py` (275 lines)  
**Website claim:** *"AI selects the highest-confidence remediation"*  
**Verdict:** 🔴 Inaccurate — this is the most important gap in the product

**What's built:**
`DecisionEngine` is a rule-based system. The docstring reads *"Rule-based Heron Core decision engine."* The logic is:
- sev1 → page on-call
- sev2 → rollback latest deployment, then escalate if blocked
- sev3 → restart component
- info → suppress/log only

The learn service feeds confidence scores from historical outcomes back into step ordering within a severity level — so if `restart_component` has a 90% success rate for `auth-service` historically, it will be ranked first. This is the most intelligent part of the current Decide step and it is genuinely valuable.

But there is no LLM, no model, no neural network, no semantic reasoning. The decision tree is hardcoded. The website's claim "AI selects" is not true today.

**The gap — and why it matters enormously:**
This is the soul of the product. An LLM-powered Decide step would:
- Read the full signal context, recent Chronicle history for the affected service, and the active postmortems
- Reason about what's different this time vs last time
- Generate a ranked list of actions with written rationale — not "rollback latest deployment" but "rollback because error rate spike pattern matches the deploy that happened 12 minutes ago"
- Ask clarifying questions when confidence is low ("This looks like a DB connection pool issue — should I scale the DB replica or restart the app?")
- Learn from the engineer's response to improve future decisions

**To close the gap:**
1. Add a `HERON_AI_PROVIDER` env var (OpenAI / Anthropic / local Ollama)
2. Build a `LLMDecisionAdapter` that constructs a prompt from: signal context + Chronicle history for the service + past decisions and outcomes + available actions from `config/actions.yaml`
3. Parse the LLM response into a ranked `DecisionPlan` with structured steps
4. Keep the rule-based engine as a fast fallback when the LLM is unavailable or confidence is below threshold
5. The learn loop already records outcomes — feed those back into the prompt as few-shot examples

This is a 3–5 day build and it transforms "smart alerting" into genuine autonomous intelligence. Everything else in the product supports it — Chronicle, Learn, the decision schema — they were all designed for this.

---

### Step 4 — Act
**File:** `app/services/reflex.py` (270 lines)  
**Website claim:** *"Approved action executed autonomously"*  
**Verdict:** ⚠️ The framework is real but nothing executes today

**What's built:**
`ReflexService` is a well-architected action execution framework with three executor types:
- `CommandExecutor` — runs shell/kubectl commands
- `ApiExecutor` — fires HTTP calls to external APIs
- `WorkflowExecutor` — triggers named workflow definitions

Actions are loaded from `config/actions.yaml`. Each action has a command template, executor type, timeout, and approval requirement. The service selects the right executor, checks policy, logs every execution to Chronicle, and returns a structured result.

However, every executor checks `dry_run` first. When `dry_run=True` (the current default), it returns `{"success": True, "details": "dry_run"}` without running anything. Nothing is actually executed today.

**The gap:**
Three things needed to make Act real:
1. **Policy gate** — add a `live_execution` flag to `config/policy.yaml` per action type and per environment. Staging can run live; prod requires an explicit whitelist.
2. **Flip the switch** — when `dry_run=False`, the `CommandExecutor` needs to actually shell out (`subprocess.run`). The hook is there — the else branch just needs implementation.
3. **Rollback safety** — before any live action, snapshot the current state so Heron can undo it. For kubectl: capture the current deployment manifest. For API calls: store the pre-action state.

The framework being clean is important — this is a half-day of work, not a redesign.

---

### Step 5 — Verify
**File:** `app/services/verify.py` (235 lines)  
**Website claim:** *"Outcome confirmed before closing"*  
**Verdict:** ✅ Accurate

**What's built:**
`VerificationService` is genuinely implemented and thoughtful. After an action executes, Verify checks whether the metric that triggered the incident has returned to baseline. It compares observed vs baseline values, supports configurable direction (decrease/increase expected), and tracks consecutive failures. If verification fails twice in a row for the same decision, it triggers the Escalate step automatically.

Results are recorded in the Learn service (feeding confidence history) and logged to Chronicle (feeding the postmortem timeline). The `check_reference` method can evaluate alarm URLs directly, which enables the DevOps Portal integration path.

**Gaps:** Minor. Verify currently requires a metric check to be explicitly configured. An LLM-enhanced Verify step could ask "did the incident actually resolve?" by looking at the full signal picture rather than a single metric comparison.

---

### Step 6 — Escalate
**File:** `app/services/escalate.py` (154 lines)  
**Website claim:** *"Human loop-in when confidence is low"*  
**Verdict:** ⚠️ The routing is real, but nothing fires today

**What's built:**
`EscalationService` is well-designed. It has deduplication (prevents the same escalation firing every 30 seconds), structured message formatting, and routes to three channels simultaneously: PagerDuty (`trigger_incident`), Slack (`send_message`), and Jira (creates a ticket with full context). The dedupe window is configurable. The structured message includes the service, severity, anomaly detail, actions attempted, and Chronicle incident link.

The orchestration logic — deciding when to escalate, which channels to use, what to include — is real and complete.

However, both `pagerduty.trigger_incident()` and `slack.send_message()` have `dry_run=True` as their default. They log the intended escalation but fire nothing.

**To close the gap:**
- Add `SLACK_WEBHOOK_URL` to `.env` and flip `dry_run=False` in `slack.py`
- Add `PAGERDUTY_ROUTING_KEY` to `.env` and flip `dry_run=False` in `pagerduty.py`
- Add a policy gate so each channel can be enabled/disabled per environment without code changes
- This is 2 hours of work and the most impactful single change to make the product feel real

---

### Step 7 — Learn
**File:** `app/services/learn.py` (189 lines)  
**Website claim:** *"Every outcome recorded in Chronicle"*  
**Verdict:** ✅ Accurate

**What's built:**
`LearnService` tracks action outcomes with a `confidence_delta` model. Every time an action succeeds or fails, its confidence score for that service/severity combination updates. Core uses these scores when ranking candidate actions — if `restart_component` has a 94% success rate for `auth-service` at sev2, it will be ranked above `rollback_latest_deployment` which might have only 60% for that service.

State persists to `data/learn_state.json` across restarts. Chronicle records every outcome as a timeline event, making the learning transparent — you can see exactly why Heron ranked actions in the order it did.

**Gaps:**
The learn loop is advisory-only today — it adjusts ranking but doesn't change the decision type (it won't decide to try a completely new action type that hasn't been seen before). An LLM-powered Decide step (Gap 3) would make the Learn loop dramatically more powerful — instead of adjusting weights in a fixed action list, the LLM would read the outcome history and generate genuinely novel strategies.

---

## Current State

---

## Intelligence Page — Full Audit & Build Plan

The Intelligence page in the dashboard has four surfaces: Learn loop summary, AI recommendations, near-miss patterns, and recent outcomes. Here is the honest state of each and exactly what it takes to make them real.

---

### Intelligence Gap 1 — Live outcomes never reach the DB

**What exists:**  
`verify.py` calls `learn_service.observe_action_outcome()` after every action verification. This correctly updates the in-memory `LearnService` and writes to `data/learn_state.json`. Core uses those scores to rank future actions. The pipeline is wired and the logic is sound.

**The problem:**  
`verify.py` does not write to the SQLAlchemy `LearnOutcome` database table. The dashboard's Intelligence page queries the DB — so the stats, top actions, and recent outcomes on the page come entirely from the seeder and never update when a real incident resolves.

**What's needed:**  
In `verify.py`, after `learn_service.observe_action_outcome()` is called, also write to the DB:

```python
from ..db.base import SessionLocal
from ..db.models import LearnOutcome
from uuid import uuid4
from datetime import datetime

with SessionLocal() as db:
    db.add(LearnOutcome(
        id=str(uuid4()),
        incident_id=plan.incident_id,
        action_type=action,
        service=learn_service_name,
        severity=plan.severity,
        outcome="success" if success else "failed",
        confidence_delta=0.05 if success else -0.03,
        recorded_at=datetime.utcnow(),
    ))
    db.commit()
```

Every real incident resolution will then feed the Intelligence page automatically.

**Effort:** 1 hour  
**Impact:** Makes the entire Intelligence page data-driven from live incidents instead of seeder data.

---

### Intelligence Gap 2 — Near-miss detection doesn't exist in the live pipeline

**What exists:**  
The `NearMiss` table exists in the DB. The dashboard shows near-miss cards. But there is zero code in `insight.py` or `sense.py` that detects near-misses from real signal data. A search for "near_miss" in both files returns nothing. Every near-miss on the dashboard today is a seeded row.

**What's needed:**  
In `InsightService.evaluate()`, after checking thresholds, add a secondary check: if a metric comes within 10% of the threshold but doesn't breach it, write a `NearMiss` record.

```python
# After threshold evaluation in insight.py
gap_pct = (threshold - observed_value) / threshold * 100
if 0 < gap_pct <= 10.0:  # within 10% but didn't breach
    with SessionLocal() as db:
        db.add(NearMiss(
            id=str(uuid4()),
            service=context.service,
            region=context.region,
            metric_name=metric_name,
            peak_value=round(observed_value, 4),
            threshold=threshold,
            gap_percent=round(gap_pct, 2),
            detected_at=datetime.utcnow(),
        ))
        db.commit()
```

This turns near-misses from static fiction into a live early-warning system. Engineers can see what almost happened before it becomes an incident.

**Effort:** 2 hours  
**Impact:** Real near-miss data surfaces automatically from every signal stream.

---

### Intelligence Gap 3 — Recommendations are static seeded strings

**What exists:**  
The `Recommendation` table is populated entirely by the seeder. The text strings (e.g. "pod_restart has 94% success rate for auth-service...") were written by hand. The confidence scores are hardcoded. No algorithm generates or updates them. They are frozen at seed time and never change.

**What's needed — Phase 1, algorithmic (no LLM):**  
Add a `generate_recommendations()` function in `repositories.py` that queries `LearnOutcome` data and applies these rules:

- **Auto-approve candidate:** service+action pair with success_rate > 85% and count > 5 → recommend adding to policy auto-approve list
- **Flagged service:** service with > 3 incidents in 7 days → flag for structural review
- **Failing action:** action with success_rate < 30% for a specific service → recommend removing from that service's policy
- **Pattern match:** same action type resolves the same service > 80% of the time → recommend setting it as the default for that service

This generates real, data-driven recommendations from actual incident history. No LLM required for this phase.

**Effort:** half day  
**Impact:** Recommendations become accurate and update as incidents resolve.

---

### Intelligence Gap 4 — There is no AI in the Intelligence page

**What exists:**  
The page title says "Intelligence" and includes a section labelled "AI recommendations." There is no AI. No LLM. No model. No inference of any kind. The recommendations are strings seeded from a Python script.

**What's needed — Phase 2, LLM-powered:**

The full AI architecture for Intelligence:

```
Chronicle DB  (incidents, outcomes, near-misses, timelines)
      ↓
ContextBuilder — assembles relevant history into a structured prompt
      ↓
LLM (Claude Sonnet 4.6 via Anthropic SDK)
      ↓
InsightParser — validates and structures the JSON response
      ↓
Recommendation table — stores generated insights with evidence links
      ↓
Intelligence page — displays with "Generated by AI" provenance
```

**Files to build:**

`app/services/ai/provider.py` — LLM provider abstraction:
```python
# Controlled by env vars:
# HERON_AI_PROVIDER = anthropic | openai | ollama
# HERON_AI_API_KEY  = sk-...
# HERON_AI_MODEL    = claude-sonnet-4-6 (default)
class AIProvider:
    def complete(self, prompt: str, system: str) -> str: ...
```

`app/services/ai/insight_generator.py` — the intelligence engine:
```python
class InsightGenerator:
    def generate(self, *, lookback_days: int = 30) -> list[dict]:
        # 1. Query Chronicle for incidents, outcomes, near-misses
        # 2. Build prompt with structured context
        # 3. Call LLM, parse structured JSON response
        # 4. Write Recommendation rows to DB
        # 5. Return generated insights
```

**The prompt structure:**
The LLM receives:
1. Recent incidents grouped by service — severity, status, auto-healed, MTTR
2. Action outcome history — what was tried, success/fail rates
3. Near-miss timeline — what almost happened
4. Current policy rules from `config/policy.yaml`
5. Output schema — so the response is parseable JSON

The LLM is asked to return:
```json
{
  "recommendations": [
    {
      "service": "auth-service",
      "action": "pod_restart",
      "confidence": 0.94,
      "rationale": "pod_restart resolves auth-service OOM events in 94% of cases across 12 incidents in the last 30 days. Pattern: OOM kill → pod_restart → resolved within 4 minutes. Consider adding to auto-approve policy for sev2.",
      "evidence": ["seed-inc-002", "seed-inc-008", "seed-inc-013"],
      "suggested_policy_change": "auto_approve: [pod_restart] for auth-service at sev2"
    }
  ],
  "risks": [
    {
      "service": "search-service",
      "risk": "Disk saturation trend — 3 near-misses in 7 days, gap narrowing from 8% to 1.2%",
      "recommended_action": "Scale storage or add disk cleanup to auto-actions"
    }
  ],
  "patterns": [
    {
      "pattern": "payment-processor incidents cluster on Tuesday/Thursday deploys",
      "confidence": 0.78,
      "suggested_action": "Add deploy gate or canary policy for payment-processor"
    }
  ]
}
```

**Why Claude Sonnet 4.6:**  
The prompt includes incident timelines, policy YAML, and outcome history — potentially thousands of tokens of context. Claude Sonnet 4.6 handles long context well, reasons about causality accurately, and produces structured JSON reliably. Using prompt caching on the Chronicle history (which changes slowly) makes repeated calls cheap — the static context is cached, only new incident data is re-sent each call.

**The trigger:**  
- `POST /api/v1/intelligence/generate` — on-demand, triggered by a "Generate Insights" button in the UI
- Optional: run automatically after every incident resolves and is closed
- Rate-limit: once per hour maximum to avoid unnecessary LLM spend

**Effort:** 2–3 days end to end  
**Impact:** The Intelligence page becomes genuinely intelligent — not a stats dashboard but an advisor that reads your incident history and tells you what to change.

---

### Intelligence — Recommended Build Order

| Step | What | Effort | Effect |
|---|---|---|---|
| 1 | Wire `verify.py` → DB `LearnOutcome` | 1 hour | Live data in the loop stats |
| 2 | Near-miss detection in `insight.py` | 2 hours | Real early-warning surface |
| 3 | Algorithmic recommendations from outcome stats | half day | Data-driven, no LLM needed |
| 4 | `app/services/ai/provider.py` | half day | LLM abstraction layer |
| 5 | `app/services/ai/insight_generator.py` + prompt | 1 day | Core AI engine |
| 6 | `POST /api/v1/intelligence/generate` endpoint | 2 hours | API trigger |
| 7 | "Generate Insights" button in dashboard UI | 1 hour | User-facing AI trigger |

After step 3 the Intelligence page has real live data.  
After step 7 it has genuine AI.  
The same `AIProvider` built in step 4 also powers the LLM Decide step (Step 3 of the closed loop) — it is the shared AI infrastructure for the entire platform.

---

## Gap 1 — Flip Slack and PagerDuty to Live

**What exists:** Both integrations are wired and connected. `slack.py` and `pagerduty.py` have full implementations but default to `dry_run=True` — they log the intended action but don't actually send.

**What's needed:**
- Accept a real Slack webhook URL via env var (`SLACK_WEBHOOK_URL`)
- Accept a real PagerDuty routing key via env var (`PAGERDUTY_ROUTING_KEY`)
- Add a policy gate in `config/policy.yaml` that controls live vs dry-run per environment
- Flip `dry_run=False` for production environments

**Impact:** Highest. This is what makes Heron a real operational tool vs a simulation.

---

## Gap 2 — Wire the Waitlist Form

**What exists:** The website CTA section has a tabbed form (Early Access / Demo / Waitlist) that shows a success state on submit but saves nothing.

**What's needed:**
- A `/api/waitlist` endpoint on the backend (or Vercel serverless function)
- Store submissions in the database (`waitlist` table: email, company, type, created_at)
- Send a confirmation email via Resend or Postmark
- Send an internal notification to Slack when someone signs up

**Impact:** Critical before sharing the site publicly. Every lead lost right now is gone.

---

## Gap 3 — Remove or Build "Sign In"

**What exists:** The nav has a "Sign in" link that points to `#access`. There is no authentication system.

**Options:**
- **Quick fix:** Remove the Sign In link from the nav entirely
- **Full build:** Implement auth using Clerk or NextAuth — email/password + Google SSO

**Impact:** Medium. Confuses visitors who click it expecting a login page.

---

## Gap 4 — Prometheus / Alertmanager Native Adapter

**What exists:** The website lists Prometheus as a native integration. The `AlertSourceAdapter` abstract base class exists in `app/services/pullers/alert_source.py` — it's designed for exactly this.

**What's needed:**
- `app/services/pullers/prometheus_puller.py` implementing `AlertSourceAdapter`
- Poll Alertmanager API (`/api/v2/alerts`) on a configurable interval
- Normalize Prometheus alert labels into Heron `SignalPayload` format
- Add `prometheus` source to `config/pullers.yaml`
- Document env vars: `PROMETHEUS_ALERTMANAGER_URL`, `PROMETHEUS_AUTH_TOKEN`

**Impact:** High. Prometheus is the most common alerting stack in the SRE world.

---

## Gap 5 — Reflex Live Execution

**What exists:** `reflex.py` has a full action execution framework with three executor types (command, API, workflow). All default to dry-run mode which simulates the action and logs it without running anything.

**What's needed:**
- Policy gate in `config/policy.yaml` to enable live execution per action type and environment
- Safe default: prod requires explicit policy approval, staging can run live
- Audit log for every live execution (Chronicle already handles this)
- Rollback mechanism for reversible actions (kubectl rollout undo, scale down)

**Impact:** This is the difference between "Heron suggests fixes" and "Heron fixes things."

---

## Gap 6 — Datadog Adapter

**What exists:** Listed as "coming soon" on the website. The `AlertSourceAdapter` interface is ready.

**What's needed:**
- `app/services/pullers/datadog_puller.py`
- Poll Datadog Events API and Monitors API
- Normalize into `SignalPayload` format
- Env vars: `DATADOG_API_KEY`, `DATADOG_APP_KEY`, `DATADOG_SITE`

---

## Gap 7 — CloudWatch Adapter

**What exists:** Listed as "coming soon" on the website.

**What's needed:**
- `app/services/pullers/cloudwatch_puller.py`
- Poll CloudWatch Alarms and EventBridge events via boto3
- Normalize into `SignalPayload` format
- Env vars: `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

---

## Gap 8 — GitHub Deployment Correlation

**What exists:** Listed as "coming soon" on the website. Nothing implemented.

**What's needed:**
- GitHub webhook receiver (`POST /webhooks/github`)
- Correlate deployment events with incident start times in Chronicle
- Surface "deploy preceded incident by N minutes" in timeline and near-miss detection
- Env vars: `GITHUB_WEBHOOK_SECRET`

**Impact:** Huge for root cause analysis. Most production incidents follow a deploy.

---

## Future Features (Not Yet Announced)

### Multi-tenancy
- `org_id` field is already on all models (foundation is in)
- Need: tenant isolation in API routes, per-org Chronicle, billing hooks

### Chronicle Search
- Full-text and semantic search across incident history
- "Has Heron seen this pattern before?" as an API call
- Foundation for the AI memory layer

### Web-based Policy Editor
- Edit `config/policy.yaml` guardrails from the dashboard UI
- Live validation, preview of what actions would be approved

### Slack Bot
- `/heron status` — current active incidents
- `/heron approve INC-1234` — approve a pending action from Slack
- Interactive incident cards with Approve / Escalate buttons

### ArgoCD / Flux Integration
- GitOps deployment correlation
- Trigger rollback via ArgoCD when Heron detects post-deploy degradation

### Semantic Runbook Matching
- `runbook_resolver.py` is a stub today
- Connect to Confluence, Notion, or a local markdown runbook directory
- Surface the most relevant runbook automatically during incident detection

### SLO / Error Budget Tracking
- Define SLOs per service
- Chronicle surfaces SLO burn rate alongside incident timelines
- Alert when error budget drops below threshold

---

## Live Service Map (Executive Topology View)

The flagship UI feature for executive stakeholders. A living map of the entire infrastructure where traffic visibly flows, latency changes colour in real time, broken connections pulse red, and every node and edge is backed by Chronicle's full incident history. Clicking anything drills into what happened, what Heron did about it, and how long it took.

Not a dashboard. Not a table. A **living canvas** of the system, updating every 5 seconds, showing what's healthy, what's degrading, and what's being fixed — right now.

---

### Zoom Hierarchy

Four levels. Start at the top, drill down by clicking.

```
Level 1 — Tenancy / Account
  All OCI tenancies, AWS accounts, GCP projects, Azure subscriptions
  Shows: inter-cloud traffic, account-level health

Level 2 — Cluster
  All K8s clusters within the tenancy
  Shows: inter-cluster traffic, cluster health, namespace groupings

Level 3 — Service  ← THE HERO LEVEL
  All services within a cluster/namespace
  Shows: animated traffic flows, latency per edge, active incidents

Level 4 — Pod
  Individual pods for a selected service
  Shows: which pods are healthy, restarting, OOMKilled, CrashLooping
```

---

### Color System (fully configurable)

**Node colors — service health:**

| Color | State | Trigger |
|---|---|---|
| `emerald-500` | Healthy | No incidents, latency normal |
| `amber-500` | Degraded | Latency elevated or error rate rising |
| `rose-500` | Critical | Active sev1/sev2 incident |
| `zinc-600` | Unknown | No data in last 60 seconds |
| `violet-500` pulsing | Being remediated | Heron is running an action right now |

**Edge colors — inter-service latency (vs baseline):**

| Color | Latency ratio | Meaning |
|---|---|---|
| `emerald-400` | < 1.2× | Normal |
| `amber-400` | 1.2× – 1.5× | Elevated |
| `orange-400` | 1.5× – 2.0× | High |
| `rose-500` | 2.0× – 3.0× | Critical |
| `rose-700` pulsing | > 3.0× or errors | Severe |
| Dashed gray | No traffic | Idle connection |
| Dashed red animated | Connection broken | Timeout / refused |

Color transitions are smooth and continuous — no hard switches. An exec watching in real time sees edges gradually warm from green through amber to red as a problem develops.

All thresholds are configurable from the Settings page. No YAML required.

---

### Traffic Animation

Three visual elements on every edge simultaneously:

**1. Edge width** — proportional to RPS. A 1,000 RPS connection is visibly thicker than a 10 RPS one.

**2. Flowing particles** — animated dots moving along the edge in the direction of traffic. More particles = higher throughput. Faster movement = lower latency (healthier). When a connection breaks, particles stop.

**3. Error sparks** — when error rate exceeds threshold, red sparks flash intermittently along the edge instead of smooth particles.

```
Normal:      ●···●···●···●···  (green, steady)
Elevated:    ●·····●·····●····  (amber, slower)
Errors:      ✦···✦···✦···✦···  (red sparks)
Broken:      - - - - - - - - -  (dashed, no movement)
Fixing:      ◌···◌···◌···◌···  (violet, pulsing — Heron is acting)
```

Implementation: SVG `stroke-dasharray` + `stroke-dashoffset` CSS animation. GPU-accelerated. No JavaScript animation loop.

---

### Node Design

```
┌─────────────────────────────┐
│  ● checkout-service         │  ← color dot = health
│                             │
│  [cpu ████░░ 43%]           │  ← mini resource bars
│  [mem ██░░░░ 31%]           │
│                             │
│  847 rps  · 0.3% err        │  ← live throughput
│  p99: 180ms                 │  ← current p99 latency
│                             │
│  ⚡ Active incident ›        │  ← badge if incident open
└─────────────────────────────┘
```

---

### Edge Tooltip (hover or click)

```
checkout-service → payment-processor
─────────────────────────────────────
Latency          p50    p95    p99
Current          12ms   48ms   180ms
Baseline         11ms   42ms   160ms
Δ               +9%   +14%   +13%

Throughput      847 rps
Error rate      0.3%
Last error      32s ago (HTTP 503)

Chronicle: 3 incidents on this edge
Last: INC-1847 · 2 days ago
Resolved: auto-healed in 4m 32s  ›
```

The Chronicle integration is the differentiator no other service map has. Every edge shows what Heron has done about past problems on that connection and how long it took to resolve.

---

### Broken Links

A broken connection gets:
- Red dashed edge, animation stopped
- `⚡` icon at midpoint
- Reason label: `Connection refused` / `Timeout 30s` / `DNS NXDOMAIN`
- Warning indicator on both endpoint nodes
- Pulsing animation if Heron is actively attempting to fix it

---

### E2E Critical Path

Select any two services. Heron highlights the critical path — the sequence of hops contributing most to end-to-end latency:

```
User → api-gateway → auth-service → user-profile → postgres
          12ms    ↗     8ms      ↗     42ms      ↗   6ms

End-to-end p99: 180ms
Bottleneck: user-profile (52% of total latency)
```

The critical path renders as a thicker, brighter overlay. Everything else dims. The bottleneck node pulses.

---

### Tech Stack

- **React Flow** (`@xyflow/react`) — node/edge graph layout, zoom/pan, custom types
- **d3-interpolate** — smooth color transitions along the latency scale
- **d3-scale** — map metric values to visual properties (width, color, opacity)
- **Framer Motion** — node entrance animations, panel transitions
- Custom SVG animated edge component for traffic particles
- Polling every 5s (v1), WebSocket push (v2)

---

### Build Plan

| Step | What | Effort |
|---|---|---|
| 1 | `GET /api/v1/tracing/graph` endpoint + data model | 1 day |
| 2 | React Flow base: nodes, edges, layout, zoom levels | 2 days |
| 3 | Custom node component (health, RPS, incident badge) | 1 day |
| 4 | Custom animated edge (particles, color interpolation) | 2 days |
| 5 | Edge + node tooltips with Chronicle history | 1 day |
| 6 | Broken link detection and visual state | half day |
| 7 | E2E critical path highlight | 1 day |
| 8 | Threshold configuration in Settings | 1 day |
| 9 | Pod-level drill-down (Level 4) | 1 day |
| 10 | WebSocket real-time updates | 1 day |

Steps 1–5 (7 days) produce a working service map that beats most commercial offerings.
Steps 6–10 complete the full vision.

---

## The Four Golden Signals

Google's SRE book defines the four metrics that matter above all others for any service. Heron collects all four automatically, per service, per service-to-service edge, and uses them as the primary input to every layer of the closed loop.

---

### What the Four Golden Signals Are

| Signal | What it measures | Why it matters |
|---|---|---|
| **Latency** | Time to serve a request (success and failure separately) | Slow is often worse than broken — users wait, queues back up |
| **Traffic** | Demand on the system (RPS, QPS, message rate) | Normalises everything else — a 1% error rate at 10 RPS is nothing; at 10,000 RPS it's catastrophic |
| **Errors** | Rate of requests that fail (explicit 5xx, implicit slow, policy violations) | Direct measure of user-facing failure |
| **Saturation** | How "full" the service is — CPU, memory, queue depth, connection pool | The leading indicator — saturation precedes failure |

**The critical nuance:** these are per-service metrics, not per-infrastructure. A `node_cpu_utilization` metric from a VM is infrastructure. `payment-processor request latency p99` is a Golden Signal. Heron must compute service-level signals from raw infrastructure metrics — that's the hard work.

---

### Signal 1 — Latency

**What to measure:**
- p50, p95, p99, p999 response time per service per endpoint
- **Successful requests and failed requests separately** — this is the most common mistake. A service that times out in 30ms is returning errors fast. Its "latency" looks fine. Its actual latency for successful requests is terrible.
- Per-endpoint breakdown (not just per-service aggregate)

**Sources in Heron:**
```
eBPF (Pixie)          → per-request timing, all protocols
Service mesh          → histogram per service pair
OTel/Jaeger traces    → span duration per operation
Prometheus histograms → `http_request_duration_seconds` bucket metrics
OCI Monitoring        → `HttpResponseTime` namespace
```

**How Heron stores it:**
```python
Signal(
    metric_name="latency_p99_ms",
    value=180.4,
    service="payment-processor",
    labels={
        "endpoint": "POST /charge",
        "status": "success",    # separate from "error"
        "source": "checkout-service",
    }
)
```

**How Insight uses it:**
Compare current p99 against a rolling baseline (7-day window, same time-of-day). If p99 > baseline × 1.5, fire an anomaly. If p99 > baseline × 3.0, fire critical.

**Baseline computation matters** — p99 at 3 AM on a Tuesday and p99 at 2 PM on a Friday are different numbers for the same healthy service. A static threshold misses both seasonal variation and gradual degradation. Heron must compute a dynamic baseline.

---

### Signal 2 — Traffic

**What to measure:**
- Requests per second per service (total)
- Requests per second per endpoint (breakdown)
- Message rate for queues (Kafka consumer lag is a derivative)
- Batch job throughput (records processed per second)

**Sources in Heron:**
```
eBPF (Pixie)          → request count per time window, all protocols
Service mesh          → `istio_requests_total` counter
Prometheus            → `http_requests_total` counter
OCI Monitoring        → `RequestCount` per load balancer / API gateway
```

**How Heron stores it:**
```python
Signal(
    metric_name="request_rate_rps",
    value=847.3,
    service="payment-processor",
    labels={"endpoint": "POST /charge"}
)
```

**How Insight uses it:**
Traffic is the normaliser. Heron uses it two ways:
1. Normalise error rates — `errors / requests` is meaningful; raw error counts are not
2. Detect traffic anomalies — a sudden drop to 0 RPS is often more alarming than a spike (circuit breaker tripped, DNS failed, upstream stopped sending)

A traffic drop to zero is a special case that must fire its own anomaly class: `traffic.complete_loss`. Many monitoring systems miss this because threshold-based alerting only checks `> threshold`, never `= 0`.

---

### Signal 3 — Errors

**What to measure — three categories:**

**Explicit errors:**
- HTTP 5xx responses
- gRPC non-OK status codes (UNAVAILABLE, INTERNAL, DEADLINE_EXCEEDED)
- Database query errors

**Implicit errors (the ones teams miss):**
- Requests that succeed but take longer than an SLO threshold (technically served, but violated the contract)
- HTTP 200 responses with error fields in the body (application-layer errors masquerading as successes)
- Retried requests — a request that succeeds on the 3rd retry is still an error from the user's perspective

**Policy errors:**
- Requests rejected by a circuit breaker
- Rate-limited requests (429)
- Auth failures (401/403)

**How Heron stores it:**
```python
# Explicit
Signal(metric_name="error_rate_pct", value=2.3,
       labels={"error_type": "http_5xx"})

# Implicit — SLO violation
Signal(metric_name="error_rate_pct", value=0.8,
       labels={"error_type": "slo_violation", "threshold_ms": "200"})

# Circuit breaker
Signal(metric_name="error_rate_pct", value=100.0,
       labels={"error_type": "circuit_breaker_open"})
```

**How Insight uses it:**
Error rate is the most direct signal. Heron fires anomalies at:
- `error_rate > 1%` for services with tight SLOs (configurable)
- `error_rate > 5%` for default services
- `error_rate = 100%` immediately, regardless of threshold (circuit breaker / complete failure)
- `error_rate > 0% AND traffic = 0` — both signals together suggest a failure mode that stopped traffic entirely

---

### Signal 4 — Saturation

**The hardest and most important golden signal.** Saturation is the leading indicator — it tells you a failure is coming before it arrives. The others are lagging indicators (you see errors after they happen). Saturation is predictive.

**What to measure — multiple dimensions:**

| Resource | Metric | Why |
|---|---|---|
| CPU | utilization % | Sustained > 85% = latency will increase |
| Memory | utilization % | Approaching 100% = OOM kill imminent |
| Disk | utilization % and I/O wait | Queue buildup slows everything |
| Network | bandwidth utilization % | Packet loss starts before 100% |
| **Connection pool** | active/max ratio | **Most impactful, most often missed** |
| **Thread pool** | queue depth | Requests queuing = latency spike coming |
| **Queue depth** | Kafka consumer lag | Backpressure building up |
| Open file descriptors | fd/max ratio | Hits limit → requests fail |

**Connection pool saturation is the most important.** The majority of database-related incidents are connection pool exhaustion. The metric to watch:

```
connection_pool_utilization = active_connections / max_connections

At 80%: latency starts increasing
At 90%: latency spikes significantly
At 95%: requests start failing (timeout waiting for connection)
At 100%: all new requests fail immediately
```

Heron must alert at 80%, not at failure. That's the whole point of Saturation as a leading indicator.

**How Heron stores it:**
```python
Signal(metric_name="connection_pool_pct", value=87.3,
       service="payment-processor",
       labels={"pool": "postgres-primary", "max": "50"})

Signal(metric_name="memory_utilization", value=0.91,
       service="auth-service",
       labels={"node": "ip-10-0-1-42"})

Signal(metric_name="kafka_consumer_lag", value=47382,
       service="data-pipeline",
       labels={"topic": "order-events", "group": "pipeline-consumer-1"})
```

**How Insight uses it:**
Saturation anomalies should fire **before** the service degrades, not after. Thresholds:
- Connection pool > 80%: warning
- Connection pool > 90%: critical — fire before requests fail
- Memory > 85%: warning
- Memory > 95%: critical — OOM kill imminent
- Kafka consumer lag growing for 5 consecutive minutes: warning (regardless of current value)
- Thread pool queue depth > 0 for 30+ seconds: warning

The Kafka consumer lag case is important: it's not the absolute value that matters, it's the trend. A lag of 10,000 that's stable is fine. A lag of 1,000 that's growing 500 per minute is a crisis within 30 minutes.

---

### The RED Method (per service-to-service edge)

Built on top of the Golden Signals, the RED method applies to every edge in the service map:

- **R**ate — requests per second on this edge
- **E**rrors — error rate on this edge
- **D**uration — latency (p99) on this edge

RED gives you a health score per service interaction, not just per service. This is what lets Heron say "checkout-service is showing 8% errors, but the actual source of errors is the checkout → payment-processor edge — payment-processor has a connection pool issue" rather than "checkout-service is broken."

---

### How Golden Signals Feed Every Layer of the Loop

```
OBSERVE (Sense)
  Ingests all 4 signals from all sources
  Normalises: eBPF → Prometheus → OCI Monitoring → custom
  Tags with service, endpoint, source, direction

DETECT (Insight)
  Computes dynamic baselines (7-day rolling, time-of-day aware)
  Fires anomalies when signals cross thresholds
  Prioritises: Saturation (leading) > Errors (critical) > Latency > Traffic

DECIDE (Core → LLM)
  Passes all 4 signals + Chronicle history to LLM
  "Saturation at 91%, errors at 2.3%, latency at 3× baseline → connection pool"
  LLM reasons about which signal is cause vs effect

ACT (Reflex)
  Actions are chosen based on which signal fired:
  - Saturation → scale up replicas, flush connection pool, increase limits
  - Errors → restart pod, rollback deployment, open circuit breaker
  - Latency → scale upstream dependency, adjust timeout/retry policy
  - Traffic drop → check circuit breaker, DNS, upstream health

VERIFY
  After action: did the anomalous signal return to baseline?
  Check all 4 signals, not just the one that triggered

LEARN
  Record: which signal fired → which action → did signals return to normal?
  Build signal-to-action confidence per service over time
```

---

### The Signals Dashboard (new page: "Golden Signals")

A dedicated page showing all 4 signals for any selected service:

```
Service: payment-processor     [last 1h] [last 6h] [last 24h]

LATENCY ───────────────────────────────────────────────────────
p50  ████████░░░░░░░  12ms  (baseline: 11ms)  ✅ normal
p95  █████████████░░  48ms  (baseline: 42ms)  ⚠️ +14%
p99  ██████████████░  180ms (baseline: 160ms)  ⚠️ +13%

TRAFFIC ───────────────────────────────────────────────────────
     ╭────╮    ╭─────────╮
 rps │    ╰────╯         ╰──── 847 rps (normal range: 200–1200)

ERRORS ────────────────────────────────────────────────────────
5xx  0.3%   ✅ below threshold (1.0%)
SLO  0.1%   ✅ requests exceeding 200ms SLO

SATURATION ────────────────────────────────────────────────────
CPU          43%  ✅
Memory       31%  ✅
Conn pool    87%  ⚠️ approaching limit (max: 50, active: 44)
Thread pool  0    ✅ no queuing
```

---

### Files to Build

```
app/services/golden_signals/
├── collector.py       ← aggregates signals from all sources per service
├── baseline.py        ← rolling baseline computation, time-of-day aware
├── anomaly.py         ← threshold evaluation (replaces static insight.py logic)
└── red.py             ← per-edge RED metrics computation

app/db/models.py additions:
  SignalBaseline      ← service, metric, window, mean, stddev, updated_at
  ServiceEdgeMetric   ← source, dest, p50, p95, p99, rps, error_rate, ts

New API endpoints:
  GET /api/v1/golden-signals/{service}   ← all 4 signals for a service
  GET /api/v1/golden-signals/edges       ← RED per service edge
  GET /api/v1/golden-signals/baselines   ← current baselines for all services
```

---

## Infrastructure Discovery Engine

The most important product expansion. Instead of requiring manual configuration, Heron points at a cloud account and discovers everything automatically — what exists, what's monitored, what has gaps, where the metrics live, and what format they're in. The customer validates and activates. The loop starts.

This repositions Heron from an incident intelligence tool to an **infrastructure intelligence layer** — the difference between "smart alerting" and "we know your entire environment."

Competitive framing: Datadog says "replace your monitoring with us." Heron says "connect to everything you already have, show you what you're missing, then autonomously resolve incidents on top."

---

### Discovery — Architecture Overview

```
Phase 1: DISCOVER
Point Heron at a cloud account (OCI, AWS, GCP, Azure)
    ↓
Inventory every resource across all compartments / regions / subscriptions:
compute, databases, K8s clusters, load balancers, networks, storage
    ↓
For each resource: what metrics are being collected? What alarms exist?
What metric namespaces are available? What's missing?
    ↓
Scan for third-party monitoring running inside the environment:
Prometheus (9090/9091/9093), Grafana (3000), Alertmanager (9093),
Datadog Agent (dd-agent process), ELK (9200), InfluxDB (8086)

Phase 2: COVERAGE MAP
Generate a visual report per resource:
🟢 Monitored with alarms configured
🟡 Metrics collected, no alarms
🔴 Resource exists, nothing watching it
⚪ Unknown / inaccessible

Phase 3: IMPORT
Connect to every monitoring source found.
Normalise all metrics into Heron SignalPayload format.
Feed into Sense. Loop starts.
```

---

### Discovery — Config Catalog + Customer Override System

The discovery engine uses a two-layer config system. Heron ships a catalog of defaults. Customers override only what differs from standard.

**File structure:**
```
config/discovery/
├── catalog/                    ← Heron built-ins, never edited by customer
│   ├── monitoring.yaml         ← Prometheus, Alertmanager, Grafana, InfluxDB
│   ├── exporters.yaml          ← Node Exporter, Kafka Exporter, Redis/Postgres Exporter
│   ├── databases.yaml          ← Postgres, MySQL, Redis, MongoDB, Cassandra
│   ├── messaging.yaml          ← Kafka, RabbitMQ, ActiveMQ, NATS
│   ├── webservers.yaml         ← Nginx, HAProxy, Traefik
│   └── kubernetes.yaml         ← kubelet, kube-state-metrics, cAdvisor
│
└── customer/                   ← Customer-owned, committed to their repo
    ├── discovery.yaml          ← Overrides + custom services + exclusions
    └── credentials.yaml.enc    ← Encrypted credentials, never plaintext
```

**Why this matters:** Every real customer runs something non-standard. Kafka on port `19092`. Prometheus behind a reverse proxy at `/internal/metrics`. Redis on `6380` because security blocked `6379`. A custom metrics API nobody else has seen. The catalog handles 90% of environments. The override file handles the rest — without touching Heron's code.

**The catalog default for a messaging service:**
```yaml
services:
  kafka:
    display_name: Apache Kafka
    default_ports:
      broker_plain: [9092]
      broker_ssl:   [9093]
      jmx:          [9999]
    metrics_exporter:
      type: kafka_exporter
      default_port: 9308
      path: /metrics
    note: "Port is highly variable. Override expected in most environments."
```

**The customer override file:**
```yaml
# config/discovery/customer/discovery.yaml
version: "1"
environment: production
cloud: oci

overrides:
  kafka:
    ports: [19092, 19093]        # non-standard broker ports
    metrics_exporter:
      port: 9309
      host: 10.0.1.88            # separate host, not co-located

  prometheus:
    host: 10.0.2.10
    port: 9091
    path: /internal/metrics      # behind reverse proxy
    auth:
      type: bearer
      token_env: PROMETHEUS_TOKEN  # resolved from env, never stored here

  node_exporter:
    ports: [9200]                # remapped, clashes with Elasticsearch default

custom_services:
  - name: payment-metrics-api
    host: 10.0.3.50
    port: 8765
    path: /v1/metrics
    format: prometheus
    labels:
      service: payment-processor

exclusions:
  hosts:
    - 10.0.99.*                  # dev subnet — ignore
  labels:
    environment: dev             # ignore anything tagged env=dev

scan:
  timeout_seconds: 30
  port_scan_enabled: true
  cidr_ranges:
    - 10.0.0.0/8
```

**The validation step — never activates silently:**
After discovery, Heron presents a review screen showing exactly what it found, what it's uncertain about, and what conflicts exist. The customer confirms, edits the override file for anything flagged, and explicitly activates. Nothing runs without approval.

---

### Discovery — Automatic Latency & Tracing Collection

Inter-service latency is the data that separates "smart alerting" from "genuine incident intelligence." Without it, Heron sees `error_rate=8%` on a service and guesses at the cause. With it, Heron sees the full call graph, identifies which hop is slow, traces it to the root service, and acts with high confidence.

There are four sources. Heron detects and connects to all of them automatically.

---

#### Source 1 — eBPF (Kubernetes, zero code change)

eBPF is the most important technology for automatic observability in 2026. It runs programs in the Linux kernel without any changes to application code. No agents injected into pods. No SDK added to application code. No code changes of any kind.

**Tool: Pixie** (open source, CNCF). Deploys as a DaemonSet. Requires kernel ≥ 4.14 (standard on any cloud provider since 2019).

What eBPF captures automatically:
- Every HTTP/1.1, HTTP/2, gRPC request between services — with latency, status code, payload size
- Every MySQL, PostgreSQL, Redis, Kafka request — with query and duration
- Every DNS resolution — with timing
- Every TCP connection — with handshake time
- Pod-to-pod traffic topology — who talks to whom, how often, how fast, how reliably

**What Heron receives per service-to-service edge:**
```
source=checkout-service, destination=payment-processor
  method=POST /charge
  p50=12ms, p95=48ms, p99=180ms
  error_rate=0.3%, rps=847
```

Updated every second. No application code changed.

**Discovery config:**
```yaml
ebpf:
  enabled: auto              # auto-enables if K8s + kernel ≥ 4.14
  engine: pixie
  deploy_daemonset: true
  protocols: [http, grpc, mysql, postgres, redis, kafka, dns]
  capture_payloads: false    # never capture request bodies — privacy default
  excluded_namespaces:
    - kube-system
    - monitoring
```

---

#### Source 2 — Service Mesh (Istio, Linkerd, Cilium)

If the customer already has a service mesh, Heron connects to it. The sidecar proxies measure every request — it's the richest possible data source.

| Mesh | Metrics endpoint | What it provides |
|---|---|---|
| Istio | `:15090/stats/prometheus` per pod | Request rate, error rate, duration histograms, mTLS events |
| Linkerd | `:4191/metrics` per pod | Same, plus retry/timeout visibility |
| Cilium | Hubble API `:4245` | L7 topology, policy enforcement events |

**Discovery config:**
```yaml
service_mesh:
  auto_detect: true
  types:
    istio:
      control_plane_namespace: istio-system
      metrics_port: 15090
    linkerd:
      control_plane_namespace: linkerd
      metrics_port: 4191
    cilium:
      hubble_relay_port: 4245
```

---

#### Source 3 — Existing Distributed Tracing Systems

If the customer already runs Jaeger, Zipkin, Tempo, or Datadog APM, Heron connects and queries trace data during active incidents.

```yaml
tracing:
  auto_detect: true
  jaeger:
    ui_port: 16686
    query_port: 16685
    collector_port: 14268
  zipkin:
    port: 9411
    api_path: /api/v2/traces
  tempo:
    port: 3200
    query_path: /api/traces
  otel_collector:
    grpc_port: 4317
    http_port: 4318
  datadog_apm:
    agent_port: 8126
```

When an incident is active, Heron automatically queries the tracing system for spans from the affected service in the last 10 minutes, surfaces the slowest traces, and feeds them into the Decide step.

---

#### Source 4 — OpenTelemetry Collector (fallback)

If eBPF is unavailable and no service mesh or tracing system is found, Heron deploys an OTel Collector as a lightweight, agentless middle layer.

The OTel Collector receives from any OTel SDK, any Prometheus exporter, or any log shipper. Normalises into OTLP format. Forwards to Heron's ingest endpoint. Customers add one environment variable to their apps (`OTEL_EXPORTER_OTLP_ENDPOINT`) — the only change required.

```yaml
otel_collector:
  deploy: auto               # deploys if no other source found
  mode: daemonset            # or sidecar | standalone
  receivers: [prometheus, otlp, jaeger, zipkin, hostmetrics]
  processors: [batch, resource_detection, tail_sampling]
  exporters: [heron_otlp]
```

---

#### Full Latency Config (Customer Override)

```yaml
# config/discovery/customer/discovery.yaml

latency:
  ebpf:
    enabled: auto
    engine: pixie
    protocols: [http, grpc, mysql, postgres, redis, kafka, dns]
    capture_payloads: false
    excluded_namespaces: [kube-system, monitoring]

  service_mesh:
    auto_detect: true

  tracing:
    auto_detect: true
    # override example:
    # jaeger:
    #   host: jaeger.monitoring.svc
    #   query_port: 16685

  otel_collector:
    deploy: auto
    existing_endpoint: ""    # set if already deployed: grpc://otel:4317

  custom_metrics:
    - name: payment_gateway_latency
      host: 10.0.3.50
      port: 9187
      format: prometheus
      label_map:
        upstream_service: destination_service

  thresholds:
    default_p99_ms: 500
    default_error_rate_pct: 2.0
    per_service:
      payment-processor:
        p99_ms: 200
        error_rate_pct: 0.5
      recommendation-engine:
        p99_ms: 1500
        error_rate_pct: 5.0
```

---

### What Inter-Service Tracing Unlocks for the Loop

Without tracing, Heron guesses:
```
error_rate on checkout-service = 8%
→ Decide: restart checkout-service (60% confidence)
```

With tracing, Heron reasons:
```
error_rate on checkout-service = 8%
p99 latency: checkout → payment-processor = 1,840ms (normal: 45ms)
p99 latency: payment-processor → postgres-primary = 1,790ms (normal: 12ms)
postgres connection_pool_utilization = 98%

→ Decide: scale payment-processor replicas +2 to relieve connection pressure
  (94% confidence — identical pattern to INC-1847 14 days ago, same fix worked)
```

The service dependency graph built from tracing data tells Heron:
- **Where** latency is accumulating — which service, which hop
- **What's upstream** of the user-facing error
- **Which service is the root cause** versus which are cascading victims
- **What the blast radius is** — how many other services are affected

This is the data that makes the LLM-powered Decide step genuinely intelligent. You cannot reason about cascading failures without a graph of how services talk to each other.

---

### The Automatic Service Map

A side effect of collecting inter-service latency is that Heron builds a **live service dependency graph** automatically. No manual configuration. No stale architecture diagrams.

Every 5 minutes, Heron knows:
- Which services exist
- Which talk to each other and how often (RPS)
- How fast (p50/p95/p99 per edge)
- How reliably (error rates per edge)
- Which services are upstream/downstream of any given incident

This becomes a feature in its own right. SREs open the Heron dashboard and see the live topology of their system, coloured by health status. That map is always more accurate than anything in Confluence because it comes from actual traffic.

---

### Discovery — Files to Build

```
app/services/discovery/
├── base.py                  ← DiscoveryAdapter abstract interface
├── report.py                ← CoverageReport model + renderer
├── catalog_loader.py        ← loads catalog + customer overrides, merges
├── validator.py             ← validates discovery.yaml against schema
├── oci/
│   ├── inventory.py         ← list all OCI resources via SDK
│   ├── coverage.py          ← check OCI Monitoring per resource
│   ├── metrics.py           ← OCI Monitoring API pull client
│   └── detector.py          ← scan for Prometheus/Grafana/Datadog in OCI
├── aws/                     ← Phase 2
├── gcp/                     ← Phase 3
└── azure/                   ← Phase 4

app/services/tracing/
├── ebpf.py                  ← Pixie DaemonSet deploy + query client
├── mesh.py                  ← Istio/Linkerd/Cilium metrics connector
├── tracing.py               ← Jaeger/Zipkin/Tempo/Datadog APM connector
├── otel.py                  ← OTel Collector deploy + OTLP ingest
└── graph.py                 ← service dependency graph builder + updater

New API endpoints:
  POST /api/v1/discovery/connect       ← submit credentials, start scan
  GET  /api/v1/discovery/status        ← scan progress
  GET  /api/v1/discovery/report        ← full coverage map
  POST /api/v1/discovery/activate      ← enable monitoring for confirmed resources
  GET  /api/v1/discovery/sources       ← all detected monitoring sources
  GET  /api/v1/tracing/graph           ← live service dependency graph
  GET  /api/v1/tracing/latency         ← p50/p95/p99 per service edge
```

---

## Priority Order

| Priority | Item | Effort | Impact |
|---|---|---|---|
| 🔴 P0 | Wire waitlist form | 2 hours | Captures leads now |
| 🔴 P0 | Flip Slack + PagerDuty live | 2 hours | Makes it a real operational tool |
| 🔴 P0 | Wire `verify.py` → DB LearnOutcome | 1 hour | Intelligence page gets live data |
| 🔴 P0 | Live near-miss detection in `insight.py` | 2 hours | Real early-warning signals |
| 🟠 P1 | Algorithmic recommendations from outcomes | half day | Data-driven intelligence, no LLM |
| 🟠 P1 | LLM provider abstraction (`ai/provider.py`) | half day | Shared AI layer for whole platform |
| 🟠 P1 | LLM insight generator + prompt engineering | 1 day | Genuine AI in Intelligence page |
| 🟠 P1 | LLM-powered Decide step (`core.py`) | 2 days | "AI selects" claim becomes true |
| 🟠 P1 | Remove "Sign in" or build auth | 30 min / 1 week | Fixes broken nav UX |
| 🟠 P1 | Prometheus adapter | 1 day | Completes native integration claim |
| 🟠 P1 | Four Golden Signals collector + baseline engine | 2 days | Foundation for all detection |
| 🟠 P1 | Dynamic baseline (rolling 7-day, time-of-day aware) | 1 day | Replaces static thresholds |
| 🟠 P1 | RED metrics per service edge | 1 day | Root cause localisation |
| 🟠 P1 | Golden Signals dashboard page | 2 days | Exec-facing signal overview |
| 🟡 P2 | Live service map — React Flow base + animated edges | 5 days | The flagship exec feature |
| 🟡 P2 | Service map — Chronicle history on edges | 1 day | Differentiator vs Kiali/Datadog |
| 🟡 P2 | Service map — E2E critical path highlight | 1 day | Exec storytelling feature |
| 🟡 P2 | Service map — threshold configuration UI | 1 day | Customer-configurable colours |
| 🟡 P2 | Service map — pod drill-down (Level 4) | 1 day | Debugging layer |
| 🟡 P2 | Discovery engine — OCI inventory + coverage | 3 days | First cloud: auto-discover everything |
| 🟡 P2 | Discovery config catalog + override system | 2 days | Works for non-standard ports/configs |
| 🟡 P2 | Discovery validation UI (coverage map page) | 2 days | Customer confirms before activation |
| 🟡 P2 | eBPF / Pixie integration (K8s latency) | 3 days | Zero-code inter-service tracing |
| 🟡 P2 | Service mesh connector (Istio/Linkerd/Cilium) | 2 days | Mesh metrics → Heron signals |
| 🟡 P2 | Tracing system connector (Jaeger/Zipkin/Tempo) | 2 days | Existing traces → incident context |
| 🟡 P2 | OTel Collector deploy + OTLP ingest | 2 days | Fallback for non-K8s environments |
| 🟡 P2 | Service dependency graph builder | 2 days | Live topology from real traffic |
| 🟡 P2 | Reflex live execution | 2 days | Full autonomous healing |
| 🟡 P2 | GitHub deployment correlation | 1 day | Root cause acceleration |
| 🟢 P3 | Discovery engine — AWS (Phase 2) | 3 days | Largest cloud market |
| 🟢 P3 | CloudWatch alert puller | 1 day | AWS-native monitoring source |
| 🟢 P3 | Discovery engine — GCP (Phase 3) | 3 days | AI/ML teams |
| 🟢 P3 | Discovery engine — Azure (Phase 4) | 3 days | Enterprise market |
| 🟢 P3 | Datadog adapter (import existing DD metrics) | 1 day | Works with, not against, Datadog |
| 🟢 P3 | Service map dashboard page | 2 days | Live topology visualisation |
| 🟢 P3 | Slack bot | 3 days | Operator experience |
| 🔵 P4 | Microsoft Teams escalation channel | 2 days | Azure/enterprise customers |
| 🔵 P4 | Chronicle semantic search | 1 week | The memory layer |
| 🔵 P4 | Web policy editor | 3 days | Self-serve configuration |
| 🔵 P4 | Runbook resolver | 2 days | Auto-surface incident context |
| 🔵 P4 | SLO / Error budget tracking | 1 week | Customer SLA visibility |
| 🔵 P4 | ArgoCD / Flux rollback integration | 2 days | GitOps-native remediation |
