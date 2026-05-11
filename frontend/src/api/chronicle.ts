import api from './client'
import type {
  ChronicleIncident,
  IncidentDetail,
  TimelineEntry,
  NearMissItem,
  TagTrendItem,
  ReportSummary,
  Annotation,
  Postmortem,
} from './types'

export async function listIncidents(params?: {
  limit?: number
  service?: string
  severity?: string
  region?: string
}): Promise<{ count: number; items: ChronicleIncident[] }> {
  const { data } = await api.get('/api/v1/chronicle/incidents', { params })
  return data
}

export async function getIncident(id: string): Promise<IncidentDetail> {
  const { data } = await api.get(`/api/v1/chronicle/incidents/${id}`)
  return data
}

export async function getTimeline(
  id: string,
  params?: { limit?: number; severity?: string; event_type?: string },
): Promise<{ count: number; items: TimelineEntry[] }> {
  const { data } = await api.get(`/api/v1/chronicle/incidents/${id}/timeline`, { params })
  return data
}

export async function addAnnotation(
  id: string,
  payload: { author: string; note: string; actor_role?: string; tags?: string[] },
): Promise<Annotation> {
  const { data } = await api.post(`/api/v1/chronicle/incidents/${id}/annotations`, payload)
  return data
}

export async function upsertPostmortem(
  id: string,
  payload: Partial<Omit<Postmortem, 'postmortem_id' | 'incident_id' | 'created_at' | 'updated_at'>>,
): Promise<Postmortem> {
  const { data } = await api.put(`/api/v1/chronicle/incidents/${id}/postmortem`, payload)
  return data
}

export async function linkIncident(
  id: string,
  linked_incident_id: string,
): Promise<ChronicleIncident> {
  const { data } = await api.post(`/api/v1/chronicle/incidents/${id}/links`, {
    linked_incident_id,
  })
  return data
}

export async function runSimulation(
  id: string,
  payload: { assumptions?: Record<string, unknown>; alternate_actions?: string[] },
) {
  const { data } = await api.post(
    `/api/v1/chronicle/incidents/${id}/simulations/what-if`,
    payload,
  )
  return data
}

export async function getReport(id: string) {
  const { data } = await api.get(`/api/v1/chronicle/reports/${id}`)
  return data
}

export async function getReportSummary(): Promise<ReportSummary> {
  const { data } = await api.get('/api/v1/chronicle/reports/summary')
  return data
}

export async function getNearMisses(
  limit = 20,
): Promise<{ count: number; items: NearMissItem[] }> {
  const { data } = await api.get('/api/v1/chronicle/insights/near-misses', {
    params: { limit },
  })
  return data
}

export async function getTagTrends(): Promise<{ count: number; items: TagTrendItem[] }> {
  const { data } = await api.get('/api/v1/chronicle/insights/tags')
  return data
}
