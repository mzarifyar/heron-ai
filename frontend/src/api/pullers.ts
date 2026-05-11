import api from './client'
import type { PullerStatus, PullerRun, JiraTicket, Signal } from './types'

export async function getPullerStatus(): Promise<PullerStatus> {
  const { data } = await api.get('/api/v1/pullers/status')
  return data
}

export async function getPullerRuns(limit = 20): Promise<{ count: number; items: PullerRun[] }> {
  const { data } = await api.get('/api/v1/pullers/runs', { params: { limit } })
  return data
}

export async function getPullerCursors() {
  const { data } = await api.get('/api/v1/pullers/cursors')
  return data
}

export async function getTickets(params?: {
  limit?: number
  page?: number
}): Promise<{ count: number; items: JiraTicket[]; total_pages?: number }> {
  const { data } = await api.get('/api/v1/pullers/tickets', { params })
  return data
}

export async function runPullerNow(source: 'jira' | 'devops_portal' | 'all') {
  const { data } = await api.post('/api/v1/pullers/run-now', null, {
    params: { source },
  })
  return data
}

export async function listSignals(limit = 50): Promise<{ items: Signal[]; count: number }> {
  const { data } = await api.get('/api/v1/sense/signals', { params: { limit } })
  return data
}

export async function getClusterHygieneLatest() {
  const { data } = await api.get('/api/v1/pullers/cluster-hygiene/latest')
  return data
}

export async function getClusterHygieneRuns() {
  const { data } = await api.get('/api/v1/pullers/cluster-hygiene/runs')
  return data
}
