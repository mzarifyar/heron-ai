import api from './client'

// ── Summary ────────────────────────────────────────────────────────────────
export async function getDashboardSummary() {
  const { data } = await api.get('/api/v1/dashboard/summary')
  return data as {
    active_incidents: number
    active_by_severity: Record<string, number>
    mttr_last_7_days: number | null
    mttr_previous_7_days: number | null
    auto_heal_rate: number
    total_incidents_this_week: number
    total_incidents_all_time: number
  }
}

export async function getAlertVolume(days = 14) {
  const { data } = await api.get('/api/v1/dashboard/alert-volume', { params: { days } })
  return data as { days: number; items: Array<{ day: string; count: number }> }
}

export async function getDashboardRecentIncidents(limit = 5) {
  const { data } = await api.get('/api/v1/dashboard/recent-incidents', { params: { limit } })
  return data as {
    items: Array<{
      id: string; title: string; severity: string; status: string
      service: string; region: string; auto_healed: boolean
      mttr_seconds: number | null; started_at: string; resolved_at: string | null
    }>
    count: number
  }
}

export async function getDashboardIntegrations() {
  const { data } = await api.get('/api/v1/dashboard/integration-status')
  return data as {
    items: Array<{
      id: string; name: string; type: string; status: string; last_synced_at: string | null
    }>
    count: number
  }
}

export async function getDashboardClusters() {
  const { data } = await api.get('/api/v1/dashboard/cluster-health')
  return data as {
    items: Array<{
      id: string; cluster_name: string; region: string; environment: string
      status: string; node_count: number; pod_count: number
      unhealthy_pods: unknown[]; last_checked_at: string
    }>
    count: number
  }
}

// ── DB-backed incidents (used by Incidents + IncidentDetail pages) ──────────
export async function listDbIncidents(params?: {
  limit?: number; offset?: number; status?: string; severity?: string; service?: string
}) {
  const { data } = await api.get('/api/v1/dashboard/incidents', { params })
  return data as {
    items: DbIncident[]; total: number; limit: number; offset: number
  }
}

export async function getDbIncident(id: string) {
  const { data } = await api.get(`/api/v1/dashboard/incidents/${id}`)
  return data as {
    incident: DbIncident
    timeline: DbTimelineEvent[]
    annotations: Array<{ id: string; author: string; content: string; created_at: string }>
    postmortem: { id: string; content: string; author: string; created_at: string } | null
    actions: Array<{
      id: string; action_type: string; status: string
      target: string; executed_at: string; result: unknown
    }>
  }
}

export interface DbIncident {
  id: string; title: string; severity: string; status: string
  service: string; region: string; environment: string
  auto_healed: boolean; mttr_seconds: number | null; duration_seconds: number | null
  started_at: string; resolved_at: string | null; created_at: string
}

export interface DbTimelineEvent {
  id: string; incident_id: string; event_type: string
  description: string; actor: string; severity: string
  timestamp: string; metadata: Record<string, unknown> | null
}

// ── Intelligence (DB-backed) ───────────────────────────────────────────────
export async function getDbLearnSummary() {
  const { data } = await api.get('/api/v1/dashboard/learn-summary')
  return data as {
    total_outcomes: number; success_rate: number
    top_actions: Array<{ action: string; service: string; count: number; success_rate: number }>
    recent_outcomes: Array<{ action: string; service: string; result: string; recorded_at: string }>
  }
}

export async function getDbRecommendations() {
  const { data } = await api.get('/api/v1/dashboard/recommendations')
  return data as {
    items: Array<{
      id: string; service: string; action: string; confidence: number
      rationale: string; status: string
    }>
    count: number
  }
}

export async function getDbNearMisses(limit = 20) {
  const { data } = await api.get('/api/v1/dashboard/near-misses', { params: { limit } })
  return data as {
    items: Array<{
      id: string; service: string; region: string; metric_name: string
      peak_value: number; threshold: number; gap_percent: number; detected_at: string
    }>
    count: number
  }
}
