import api from './client'

export interface SignalReading {
  current: number
  baseline_mean: number | null
  baseline_p99: number | null
  ratio_vs_baseline: number
  severity: 'ok' | 'warning' | 'critical' | 'unknown'
}

export interface ServiceGoldenSignals {
  service: string
  timestamp: string
  latency: {
    p50_ms: number; p95_ms: number; p99_ms: number
  } & SignalReading
  traffic: {
    rps: number; zero_traffic: boolean
  } & SignalReading
  errors: {
    rate_pct: number
  } & SignalReading
  saturation: {
    cpu_pct: number; memory_pct: number; connection_pool_pct: number
    cpu_severity: string; memory_severity: string; pool_severity: string
  }
}

export interface ServiceSummaryRow {
  service: string
  overall_health: 'ok' | 'warning' | 'critical' | 'unknown'
  latency_p99_ms: number
  error_rate_pct: number
  rps: number
  pool_pct: number
  latency_severity: string
  error_severity: string
  saturation_severity: string
}

export interface EdgeMetric {
  source: string; dest: string; cluster: string
  p50_ms: number; p95_ms: number; p99_ms: number
  rps: number; error_rate_pct: number
  timestamp: string; health: 'ok' | 'warning' | 'critical'
}

export async function getGoldenSignalsSummary() {
  const { data } = await api.get('/api/v1/golden-signals/summary')
  return data as { items: ServiceSummaryRow[]; count: number; computed_at: string }
}

export async function getServiceSignals(service: string) {
  const { data } = await api.get(`/api/v1/golden-signals/${service}`)
  return data as ServiceGoldenSignals
}

export async function getEdgeMetrics() {
  const { data } = await api.get('/api/v1/golden-signals/edges/all')
  return data as { items: EdgeMetric[]; count: number }
}

export async function recomputeBaselines() {
  const { data } = await api.post('/api/v1/golden-signals/baselines/recompute')
  return data as { baselines_written: number; computed_at: string }
}
