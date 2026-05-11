import api from './client'
import type { LearnSummary, LearnRecommendation, JiraAuthStatus, ExplainEvent } from './types'

export async function getLearnSummary(): Promise<LearnSummary> {
  const { data } = await api.get('/api/v1/ops/learn/summary')
  return data
}

export async function getLearnRecommendations(): Promise<{
  count: number
  items: LearnRecommendation[]
}> {
  const { data } = await api.get('/api/v1/ops/learn/recommendations')
  return data
}

export async function getJiraAuthStatus(): Promise<JiraAuthStatus> {
  const { data } = await api.get('/api/v1/jira-auth/status')
  return data
}

export async function getClusterAccessStatus() {
  const { data } = await api.get('/api/v1/ops/cluster-access/status')
  return data
}

export async function getDevOpsAdminStatus() {
  const { data } = await api.get('/api/v1/ops/devops-admin/status')
  return data
}

export async function getExplainEvents(
  limit = 50,
): Promise<{ count: number; items: ExplainEvent[] }> {
  const { data } = await api.get('/api/v1/explain/events', { params: { limit } })
  return data
}

export async function refreshOperatorToken() {
  const { data } = await api.post('/api/v1/ops/operator-token/refresh')
  return data
}
