import api from './client'
import type { HealthResponse } from './types'

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await api.get('/healthz')
  return data
}

export async function getReadiness(): Promise<HealthResponse> {
  const { data } = await api.get('/readyz')
  return data
}
