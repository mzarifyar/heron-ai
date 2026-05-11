// ── Chronicle ──────────────────────────────────────────────────────────────

export type IncidentStatus = 'open' | 'resolved' | 'postmortem'
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'

export interface ChronicleIncident {
  incident_id: string
  service: string
  environment: string
  region: string
  org_id: string
  status: IncidentStatus
  severity: Severity
  summary: string
  started_at: string
  updated_at: string
  linked_incidents: string[]
  decision_ids: string[]
  tags: string[]
}

export interface TimelineEntry {
  event_id: string
  incident_id: string
  happened_at: string
  component: string
  event_type: string
  summary: string
  severity: Severity
  signal_id: string | null
  decision_id: string | null
  action_id: string | null
  correlation_ids: Record<string, string>
  metadata: Record<string, unknown>
  tags: string[]
  near_miss: boolean
}

export interface Annotation {
  annotation_id: string
  incident_id: string
  author: string
  note: string
  created_at: string
  tags: string[]
  attachments: string[]
}

export interface Postmortem {
  postmortem_id: string
  incident_id: string
  template_version: string
  summary: string
  impact: string
  root_cause: string
  timeline_summary: string
  lessons_learned: string[]
  follow_up_actions: string[]
  created_at: string
  updated_at: string
}

export interface IncidentDetail {
  incident: ChronicleIncident
  annotations: Annotation[]
  postmortem: Postmortem | null
}

export interface NearMissItem {
  incident_id: string
  service: string
  near_miss_count: number
  latest_event_type: string
}

export interface TagTrendItem {
  tag: string
  count: number
}

export interface ReportSummary {
  // Backend field names (from chronicle_service.report_summary())
  incidents_total?: number
  incidents_open?: number
  incidents_resolved?: number
  near_miss_total?: number
  // Convenience aliases used in the UI
  total_incidents?: number
  open_incidents?: number
  resolved_incidents?: number
  mean_ttx_seconds?: number | null
  action_failure_rate?: number
  top_services?: Array<{ service: string; count: number }>
  severity_breakdown?: Record<string, number>
}

// ── Pullers ────────────────────────────────────────────────────────────────

export interface PullerSourceState {
  source: string
  enabled: boolean
  running: boolean
  last_run_at: string | null
  last_status: string | null
  last_error: string | null
  interval_seconds: number
}

export interface PullerStatus {
  // Backend shape: { scheduler: { enabled, running }, sources: PullerSourceState[] }
  scheduler?: { enabled: boolean; running: boolean }
  sources?: PullerSourceState[] | Record<string, PullerSourceState>
}

export interface PullerRun {
  run_id: string
  source: string
  started_at: string
  finished_at: string | null
  status: string
  summary: Record<string, unknown>
}

export interface JiraTicket {
  key: string
  summary: string
  status: string
  severity: string | null
  created_at: string
  updated_at: string
  labels: string[]
}

// ── Learn / Ops ────────────────────────────────────────────────────────────

export interface LearnSummary {
  total_outcomes: number
  success_rate: number
  top_actions: Array<{ action: string; success_rate: number; count: number }>
  recent_outcomes: Array<{
    action: string
    service: string
    result: string
    recorded_at: string
  }>
}

export interface LearnRecommendation {
  action: string
  service: string
  confidence: number
  rationale: string
}

// ── Signals ────────────────────────────────────────────────────────────────

export interface Signal {
  signal_id: string
  type: string
  detected_at: string
  summary: string
  details: Record<string, unknown>
  context: {
    org_id: string
    service: string
    tier: string
    environment: string
    region: string
    component: string | null
    labels: Record<string, string>
  }
}

// ── Health ─────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string
  version?: string
  environment?: string
}

// ── Explain ────────────────────────────────────────────────────────────────

export interface ExplainEvent {
  event_id: string
  event_type: string
  component: string
  summary: string
  severity: string
  happened_at: string
  metadata: Record<string, unknown>
}

// ── Jira Auth ──────────────────────────────────────────────────────────────

export interface JiraAuthStatus {
  configured: boolean
  token_source: string | null
  base_url: string | null
  last_checked: string | null
}
