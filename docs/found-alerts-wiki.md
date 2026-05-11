Digital Assistant Alerts Inventory and Operations Guide

Introduction
This page is the single source of truth for Digital Assistant (DA) alerts/alarms that protect service health across infrastructure and application layers. It explains what each alarm is watching, why it exists, the thresholds/pending durations that drive signal-to-noise, and where the Terraform code lives. You can use this document to understand current coverage, triage incidents, and plan changes to alerting.

Goals and Audience
- Goals: provide a readable catalog of alarms; document operational intent, thresholds, and runbooks; show where to edit alarms and how to validate changes end‑to‑end.
- Audience: SREs, on-call engineers, service owners, and developers who need to tune, troubleshoot, or extend alerting.

Scope and Sources
- Scanned paths:
  - bots-terraform (Terraform alarm definitions)
  - oda-control-plane-app/services/digital-assistant-monitoring (emits metrics; no alarm resources here)
- Alarm types:
  - telemetry_alarm (T2 alarms via MQL on T2 metrics)
  - aws_monitoring_alarm (AWS Monitoring alarms on AWS metrics)

How Alarms Are Wired End-to-End
1) digital-assistant-monitoring emits rich ATP and platform metrics (e.g., atp_*, kube_*, dynent_es.*, qna_es.*, http_status_*). These feed T2.
2) Terraform in bots-terraform defines alarms using MQL queries (telemetry_alarm) or AWS Monitoring queries (aws_monitoring_alarm). Alarms specify:
   - project/fleet (routing and ownership), severity, pending_duration (debounce), dedupe_key, Jira destinations.
3) At runtime, alarms evaluate sampled series, raise incidents, and route to Jira SD projects/components/items defined per category or per alarm.

Severity, Thresholds, and Pending Duration
- Severity is tuned per environment: many alarms set Prod=2/3 and lower severity for non‑prod. Pending duration (e.g., PT5M, PT15M, PT1H) prevents flapping.
- Thresholds are chosen to surface customer-impacting conditions with actionable follow‑ups (linked runbooks). When tuning, change only one variable at a time (threshold or pending), then validate in T2 Explorer.

Common Alarm Fields (Quick Reference)
- project/fleet: logical ownership and Grafana filtering (e.g., DigitalAssistant, hostmetrics; fleet often clusterName or functional fleet).
- query: MQL or AWS query that computes a boolean/threshold comparison over a time window.
- pending_duration: minimum sustained breach before firing.
- severity: 2 (higher), 3, or 4 (warning). Non‑prod usually uses local.non_prod_default_severity.
- labels: optional labels used by internal automation (e.g., OS updater).

Making Changes Safely (Process)
1) Locate the alarm module (file path listed below). Update thresholds or pending_duration in a PR.
2) Validate: 
   - Terraform plan in a non‑prod account/region.
   - Use T2 MQL Explorer to replay series against the new threshold.
3) Deploy: apply change in a low‑risk region first (e.g., d0/d1), observe, then promote.
4) Runbooks: ensure linked runbooks exist and reflect the changed behavior.

Runbook Links
Every alarm includes a Refer Runbook link (templated by realm). Use these to triage. If a runbook is missing or stale, file a task to update it as part of the change.

Limitations and Gotchas
- aws1 vs other realms: some alarms are disabled outside aws1 or use different pending values.
- Cluster lists: many modules compose local.cluster_names from dp and ss cp clusters—ensure target clusters are present in inputs.
- CDA‑gated alarms: some alarms (e.g., MAX namespace) are enabled only when var.is_cda_tenant is true.
- Exclusions: some service or namespace patterns are explicitly excluded to avoid noisy pods.

Using this Catalog
- For a given symptom (e.g., high 5xx on ingress), search this page for the category (Ingress) and alarm name; follow the runbook.
- When adding a new alarm, decide the right category module (k8s, ingress, services, etc.), severity, pending, and again include a runbook.

— — —

Bots Terraform — Alerts by Category

Infrastructure — VM Hosts
Purpose
Monitors the health and saturation of the Control Plane and Admin VMs (CPU, disk, memory, host reachability). These alarms protect essential control paths like management APIs, scheduling, and OS baselines.

File: bots-terraform/shepherd/shared_modules/t2/alarms/hostvm/cp_vm_alarms.tf
- cp_vm_host_cpu_utilization_99_percent
  • Does: CP VM CPU > 99% for 15m; requires uptime > 20m
  • Threshold: ((sar.cpu-load.all.synth.utilized[1m].mean() > 99) && (sar.os.uptime[1m].min() > 1200)) == 1
  • Pending: PT15M • Severity: Prod=3
- cp_vm_host_disk_capacity_usage_90_percent
  • Does: CP VM disk usage > 90% for 15m
  • Threshold: sar.filesystems.fsused-percent.max[1m].mean() > 90
  • Pending: PT15M • Severity: Prod=3
- admin_vm_host_cpu_utilization_99_percent
  • Does: Admin VM CPU > 99% for 15m; uptime > 20m
  • Threshold: same as CP CPU alarm
  • Pending: PT15M • Severity: Prod=3
- admin_vm_host_disk_capacity_usage_90_percent
  • Does: Admin VM disk usage > 90% for 15m
  • Threshold: fsused-percent.max mean > 90
  • Pending: PT15M • Severity: Prod=3
- cp_vm_host_disk_capacity_usage_75_percent (STIG early warn)
  • Does: CP VM disk usage > 75% for 15m
  • Threshold: fsused-percent.max mean > 75
  • Pending: PT15M • Severity: Prod=4
- admin_vm_host_disk_capacity_usage_75_percent (STIG early warn)
  • Does: Admin VM disk usage > 75% for 15m
  • Threshold: fsused-percent.max mean > 75
  • Pending: PT15M • Severity: Prod=4
- cp_vm_host_unresponsive
  • Does: CP VM host unresponsive (no sar) for 10m
  • Threshold: sar.cpu-load.sys.min[1m].groupBy(host).absent(12h) == 1
  • Pending: PT10M • Severity: Prod=2
- admin_vm_host_unresponsive
  • Does: Admin VM host unresponsive for 30m
  • Threshold: sar.cpu-load.sys.min absent(12h) == 1
  • Pending: PT30M • Severity: Prod=2
- cp_vm_host_memory_usage
  • Does: CP VM memory > 95% (20m in aws1; 60m otherwise)
  • Threshold: sar.memory.memutilized-percent[1m].mean() > 95
  • Pending: PT20M (aws1) • Severity: Prod=2
- admin_vm_host_memory_usage_over_90_percent
  • Does: Admin VM memory > 90% for 30m
  • Threshold: sar.memory.memutilized-percent[1m].mean() > 90
  • Pending: PT30M • Severity: Prod=2
Operational Notes
- CPU > 99% for sustained windows usually maps to runaway processes, unexpected workload spikes, or noisy neighbors. Use OS telemetry dashboards.
- Disk capacity > 90% can quickly degrade services (temp/log growth). Check large directories and rotate/cleanup.

Infrastructure — Kubernetes
Purpose
Surfaces degraded cluster health (nodes, pods, quotas) and missing telemetry to catch systemic failures early across DP and some SS-CP clusters.

File: bots-terraform/shepherd/shared_modules/t2/alarms/k8s/k8s_alarms.tf
- more_than_20_percent_of_the_pods_are_down_in_the_cluster
  • Does: > 20% pods down for 5m • Threshold: kube_pod_down_percent mean > 20 • Pending: PT5M • Sev: Prod=2
- more_than_5_percent_of_the_pods_got_evicted_in_the_cluster
  • Does: > 5% pod evictions for 15m • Threshold: kube_evicted_pod_percent mean > 5 • Pending: PT15M • Sev: Prod=3
- more_than_one_node_is_down
  • Does: node alive < 1 • Threshold: kube_node_alive_status groupBy(node_ip) mean < 1 • Pending: PT5M • Sev: Prod=2
- node_in_disk/memory/pid_pressure_condition
  • Does: pressure > 0 for 15m • Threshold: kube_node_pressure_status_count{condition=...} mean > 0 • Pending: PT15M • Sev: Prod=3
- node_in_pressure_condition (combined)
  • Does: any pressure for 1h • Threshold: condition =~ Disk|Memory|PID • Pending: PT1H • Sev: Prod=3
- one_or_more_pod_is_down_in_the_cluster
  • Does: pod down (exclusions) for 1h • Threshold: kube_pod_down_count > 0 • Pending: PT1H • Sev: Prod=2
- replica not healthy (deployment/statefulset/daemonset)
  • Does: unavailable replicas >=1 for 15m • Pending: PT15M • Sev: Prod=3
- resource_usage_is_critical
  • Does: cluster requests > 90% • Pending: PT15M • Sev: Prod=2
- maintenance/read-only/PVC/namespace quota/metrics absent
  • Address hygiene and capacity signals • Pending: PT5–15M • Sev: Prod=2–3
- MAX namespace (CDA) OOM/pending/restarts
  • Spot peaks and memory limits gaps quickly • Pending: 1–5m • Sev: Prod=3
- EKS host unresponsive (ODA/CDA)
  • Detects nodes with missing sar for 2h • Pending: PT15M • Sev: Prod=2
Operational Notes
- Evictions: often caused by disk pressure or memory limits. Cross-check node pressure alarms.
- Metrics absent indicates stack issues (prometheus/kube-state-metrics). Prioritize restoring visibility.

Ingress
Purpose
Detect ingress saturation and error bursts at NGINX and Traefik layers before it impacts end-user traffic.

File: bots-terraform/shepherd/shared_modules/t2/alarms/ingress/ingress_alarms.tf
- ingress_connections_per_contoller
  • NGINX ingress connections per controller > 13,000 (PT5M) • Sev: Prod=3
- traefik_ingress_connections_per_pod
  • Traefik pod connections > 6,000 (PT5M) • Sev: Prod=2
- traefik_ingress_downstream_5xx_errors
  • 5xx > 10 over 10m, PT1M pending • Sev: Prod=2
Operational Notes
- Investigate backend health (5xx) vs. front‑door saturation (connections). Scale or shed load as needed.

Load Balancers
Purpose
Protects AWS flexible LBs from saturation and monitors SLB memory usage to avoid restarts.

File: bots-terraform/shepherd/shared_modules/t2/alarms/ingress/loadbalancer_alarms.tf
- dp/cp_lb_bandwidth_reaching_max: RX > 95% (PT1M) • Sev: Prod=2
- dp_lb_bandwidth_reaching_70_percent_max: RX > 70% (CDA) (PT1M) • Sev: Prod=3
- max_slb_high_memory_usage / oda_slb_high_memory_usage: > 5GB (PT1M) • Sev: Prod=2
Operational Notes
- RX calculation converts bytes to bits/sec (rx_bytes/60*8). Consider LB shape bump or traffic engineering.

DNS Pool
Purpose
Prevents ATP DNS exhaustion which breaks connectivity for new sessions.

File: bots-terraform/shepherd/shared_modules/t2/alarms/dns/dns-entries.tf
- dns_pool_availability_less_than_10
  • Available ATP DNS entries < 10 for 20m • Sev: Prod=2
Operational Notes
- Typically addressed by expanding the DNS pool or reducing churn. See the DNS runbook.

ODA Instance Limits
Purpose
Guards per‑ATP service instance limits (Dev 1024, Prod 512) to avoid provisioning failures.

File: bots-terraform/shepherd/shared_modules/t2/alarms/limits/oda_instance_limit_alarms.tf
- development_instances_count_greater_than_90_of_max_limit_1024: > 922 (PT1M) • Sev: Prod=3
- prod_instances_count_greater_than_90_of_max_limit_512: > 461 (PT1M) • Sev: Prod=3
Operational Notes
- Source metrics (si_cnt_*) are computed by the ATP collectors. Before scaling, confirm shared vs. instance ATP utilization.

Services
Purpose
Monitors availability, HTTP error rates, request spikes, ODL error volume, chat/agent capacity, DR and Insights data flows.

File: bots-terraform/shepherd/shared_modules/t2/alarms/services/services_alarms.tf
- bots_dt_services_availability_5m / 15m: availability < 99% • Sev: 3/2
- bots_rt_services_availability_5m / 15m: availability < 99% • Sev: 3/2
- http 5xx/4xx rates: 5xx > 5%; 4xx > 10% (connectors 1%) • Sev: 2/4
- request spikes: management APIs > 1500/min • Sev: 4
- ODL errors: > 500/200 • Sev: 2/3
- Chat/Agent connections approaching limits • Sev: 2/3
- DR export/import and Insights export/import failures (>=1 or >3/10m) • Sev: 3/2
Operational Notes
- Pair rate-based alarms with recent deploys and upstream dependency health.

Kafka
Purpose
Detects broker liveness, consumer lag and stability, ISR health, controller leadership, replication, and client failure rates.

File: bots-terraform/shepherd/shared_modules/t2/alarms/kafka/kafka_alarms.tf
- Broker down (PT2M, Sev 2)
- Consumer lag (pipelines/chatserver/connectors/insights/committer/fn-deployer) with tuned thresholds and pendings
- ISR shrink (>50/min), no active controller (!= 1), under‑replicated (!= 0), offline partitions (> 0)
- Consumer/producer failure ratios > 10%
Operational Notes
- Lag triage: identify the lagging group and partition, check consumer health, rebalance or scale where needed.

Elasticsearch
Purpose
Protects the search clusters (Dynent, QnA) for CPU/JVM saturation, indexing/search surges, shard pressure, and cluster health.

File: bots-terraform/shepherd/shared_modules/t2/alarms/elasticsearch/elasticsearch_alarms.tf
- CPU > 70% (20m), JVM ratio > 0.8 (15m), High index/search rates, Unassigned shards > 100 (15m), Shards per node > 1190 (15m), Cluster health != green (10m)
Operational Notes
- Unassigned shards often follow node loss or resource exhaustion. Follow the shard recovery runbooks.

Memcached
Purpose
Ensures cache clusters (Sessions/Skillstore) are alive and not saturated on connections or memory.

File: bots-terraform/shepherd/shared_modules/t2/alarms/memached/memcached_alarms.tf
- Liveness down; Connection usage > 95%; Memory usage > 85–90%
Operational Notes
- Memory pressure can come from key cardinality or TTL changes; consider eviction policy and sizing.

Speech
Purpose
Detects hard outages (no active servers) or growing queues that impact speech workloads.

File: bots-terraform/shepherd/shared_modules/t2/alarms/speech/speech_alarms.tf
- All speech pods down (PT1M, Sev 2)
- Queue growing (> 0), pending PT1M/3M, Sev 3

oda-control-plane-app/services/digital-assistant-monitoring
Purpose
This service emits the metrics referenced by the alarms above (e.g., atp_* session, tablespace, limits; kube_*; http_*). There are no Terraform alarms in this repo path; tuning and routing are done in bots‑terraform. When changing collectors (new metrics or dimensions), coordinate with alarm owners.

Change Log and Ownership
- Owners: DA SRE team; per‑module owners match project/fleet mapping.
- Before altering severities/thresholds, inform on-call rotation and review runbooks.
- Keep runbooks accurate and linked; update JIRA routing if ownership changes.
