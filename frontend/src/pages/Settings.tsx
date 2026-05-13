import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Settings2, FileCode, Shield, Gauge, Server, Save, RefreshCw, CheckCircle, XCircle } from 'lucide-react'
import api from '../api/client'
import PageHeader from '../components/layout/PageHeader'
import Tabs from '../components/ui/Tabs'
import Card, { CardHeader } from '../components/ui/Card'
import Badge from '../components/ui/Badge'
import { getHealth } from '../api/health'

function EnvVar({ name, value, secret }: { name: string; value?: string; secret?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-zinc-800/60 last:border-0">
      <code className="text-xs text-violet-400">{name}</code>
      <span className="text-xs text-zinc-500 font-mono ml-4">
        {secret ? '••••••••' : (value || <span className="text-zinc-700">not set</span>)}
      </span>
    </div>
  )
}

function GeneralTab() {
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: getHealth })
  return (
    <div className="space-y-4 mt-4">
      <Card>
        <CardHeader title="Runtime" subtitle="Current Cortex service configuration" />
        <div className="space-y-0">
          <EnvVar name="CORTEX_ENV" value={health?.environment} />
          <EnvVar name="CORTEX_API_PORT" value="8080" />
          <EnvVar name="CORTEX_LOG_LEVEL" value="INFO" />
          <EnvVar name="CORTEX_TELEMETRY_BUFFER_SIZE" value="512" />
          <EnvVar name="CORTEX_DEMO_MODE" value="see .env" />
        </div>
      </Card>

      <Card>
        <CardHeader title="Key Variables" subtitle="Set in your .env file" />
        <div className="space-y-0">
          <EnvVar name="JIRA_BASE_URL" value="configured" secret />
          <EnvVar name="JIRA_BEARER_TOKEN" value="configured" secret />
          <EnvVar name="CORTEX_INGEST_TOKEN" value="optional" secret />
          <EnvVar name="CORTEX_ALERT_SOURCE_HOST" value="optional" />
          <EnvVar name="OPERATOR_ACCESS_TOKEN" value="optional" secret />
        </div>
      </Card>

      <Card>
        <CardHeader title="Status" />
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${health?.status === 'ok' ? 'bg-emerald-400' : 'bg-zinc-600'}`}
          />
          <span className="text-sm text-zinc-300">
            API {health?.status === 'ok' ? 'healthy' : 'unknown'}
          </span>
          {health?.version && (
            <Badge variant="muted">{health.version}</Badge>
          )}
        </div>
      </Card>
    </div>
  )
}

function ConfigEditor({ configName, title, subtitle }: { configName: string; title: string; subtitle: string }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<string | null>(null)
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null)
  const [saveOk, setSaveOk] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['config', configName],
    queryFn: () => api.get(`/api/v1/ops/config/${configName}`).then(r => r.data as { content: string }),
    staleTime: 30_000,
  })

  const content = draft ?? data?.content ?? ''

  const previewMut = useMutation({
    mutationFn: () => api.post('/api/v1/ops/config/policy/preview', { content }),
    onSuccess: (res) => setPreview(res.data),
  })

  const saveMut = useMutation({
    mutationFn: () => api.put(`/api/v1/ops/config/${configName}`, { content }),
    onSuccess: () => {
      setSaveOk(true)
      setDraft(null)
      qc.invalidateQueries({ queryKey: ['config', configName] })
      setTimeout(() => setSaveOk(false), 3000)
    },
  })

  const isDirty = draft !== null && draft !== data?.content

  return (
    <Card>
      <div className="flex items-start justify-between mb-4">
        <CardHeader title={title} subtitle={subtitle} />
        <div className="flex items-center gap-2 shrink-0">
          {configName === 'policy' && (
            <button
              onClick={() => previewMut.mutate()}
              disabled={previewMut.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-zinc-400 bg-zinc-800 border border-zinc-700 rounded-lg hover:bg-zinc-700 transition-colors"
            >
              {previewMut.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Shield className="w-3 h-3" />}
              Preview
            </button>
          )}
          <button
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending || !isDirty}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-colors ${
              saveOk
                ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
                : isDirty
                ? 'text-violet-300 bg-violet-600/20 border-violet-500/40 hover:bg-violet-600/30'
                : 'text-zinc-600 bg-zinc-800 border-zinc-700 cursor-not-allowed'
            }`}
          >
            {saveMut.isPending ? <RefreshCw className="w-3 h-3 animate-spin" /> :
             saveOk ? <CheckCircle className="w-3 h-3" /> : <Save className="w-3 h-3" />}
            {saveOk ? 'Saved' : 'Save'}
          </button>
        </div>
      </div>

      {saveMut.error && (
        <div className="flex items-center gap-2 mb-3 p-2.5 bg-rose-500/10 border border-rose-500/20 rounded-lg text-xs text-rose-400">
          <XCircle className="w-3.5 h-3.5 shrink-0" />
          {String((saveMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? saveMut.error)}
        </div>
      )}

      {isLoading ? (
        <div className="h-64 bg-zinc-800/50 rounded-lg animate-pulse" />
      ) : (
        <textarea
          value={content}
          onChange={e => setDraft(e.target.value)}
          spellCheck={false}
          className="w-full h-80 bg-zinc-900 border border-zinc-700 rounded-lg p-4 text-xs text-zinc-300 font-mono resize-y focus:outline-none focus:border-violet-500 leading-relaxed"
        />
      )}

      {isDirty && (
        <p className="text-xs text-amber-400 mt-2">Unsaved changes — click Save to apply.</p>
      )}

      {/* Policy preview panel */}
      {preview && configName === 'policy' && (
        <div className="mt-4 border-t border-zinc-800 pt-4 space-y-3">
          <p className="text-xs font-medium text-zinc-400">Preview — what this policy would approve:</p>

          {!(preview as { valid: boolean }).valid ? (
            <p className="text-xs text-rose-400">{String((preview as { error: string }).error)}</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <p className="text-zinc-500 mb-1">Auto-mitigate</p>
                  <p className={`font-medium ${(preview as { summary: { auto_mitigate: boolean } }).summary.auto_mitigate ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {(preview as { summary: { auto_mitigate: boolean } }).summary.auto_mitigate ? 'Enabled' : 'Disabled'}
                  </p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <p className="text-zinc-500 mb-1">Max consecutive actions</p>
                  <p className="font-medium text-zinc-200">{String((preview as { summary: { max_consecutive_actions: number } }).summary.max_consecutive_actions)}</p>
                </div>
              </div>

              <div className="bg-zinc-800/50 rounded-lg p-3 text-xs">
                <p className="text-zinc-500 mb-2">Action approval status</p>
                <div className="space-y-1">
                  {((preview as { action_rules: Array<{ action: string; enabled: boolean; requires_approval: boolean }> }).action_rules || []).map((a) => (
                    <div key={a.action} className="flex items-center justify-between">
                      <code className="text-violet-400">{a.action}</code>
                      <div className="flex items-center gap-2">
                        {!a.enabled && <span className="text-rose-400">disabled</span>}
                        {a.requires_approval
                          ? <span className="text-amber-400">requires approval</span>
                          : <span className="text-emerald-400">auto</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {(preview as { live_execution: { enabled: boolean; live_environments: string[]; live_actions: string[] } }).live_execution?.enabled && (
                <div className="bg-zinc-800/50 rounded-lg p-3 text-xs">
                  <p className="text-zinc-500 mb-1">Live execution</p>
                  <p className="text-emerald-400">
                    Environments: {(preview as { live_execution: { live_environments: string[] } }).live_execution.live_environments.join(', ') || 'none'}
                  </p>
                  <p className="text-emerald-400">
                    Actions: {(preview as { live_execution: { live_actions: string[] } }).live_execution.live_actions.join(', ') || 'none'}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Card>
  )
}

function PolicyTab() {
  return (
    <div className="space-y-4 mt-4">
      <ConfigEditor
        configName="policy"
        title="Policy Engine"
        subtitle="Edit guardrail rules — click Preview to see what actions would be approved before saving"
      />
      <ConfigEditor
        configName="actions"
        title="Actions Playbook"
        subtitle="Registered Reflex actions — commands, timeouts, retries, and fallback chains"
      />
    </div>
  )
}

function ThresholdsTab() {
  return (
    <div className="space-y-4 mt-4">
      <Card>
        <CardHeader
          title="Anomaly Detection Thresholds"
          subtitle="Configured in config/thresholds.json"
        />
        <p className="text-sm text-zinc-500 mb-4">
          Insight uses these thresholds to classify incoming signals as anomalies before passing them to Core.
        </p>
        <div className="grid grid-cols-2 gap-3">
          {[
            { label: 'CPU saturation', value: '80%' },
            { label: 'Error rate', value: '2%' },
            { label: 'Memory pressure', value: '85%' },
            { label: 'Disk I/O wait', value: '50%' },
            { label: 'Latency p99', value: '500ms' },
            { label: 'Pod crash threshold', value: '2 restarts' },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-center justify-between bg-zinc-800/60 rounded-lg px-3 py-2">
              <span className="text-xs text-zinc-400">{label}</span>
              <span className="text-xs font-mono text-zinc-300">{value}</span>
            </div>
          ))}
        </div>
        <p className="text-xs text-zinc-600 mt-3">
          Edit{' '}
          <code className="text-zinc-500">config/thresholds.json</code> and restart to apply changes.
        </p>
      </Card>
    </div>
  )
}

function ControlPlaneTab() {
  return (
    <div className="space-y-4 mt-4">
      <Card>
        <CardHeader
          title="Control Plane"
          subtitle="Region and environment metadata (config/control_plane.json)"
        />
        <p className="text-sm text-zinc-500 mb-4">
          The control plane defines which regions and environments Cortex manages, and which roles
          are authorized for each action type.
        </p>
        <div className="space-y-2">
          {[
            { label: 'Regions', value: 'us-east-1, us-west-2' },
            { label: 'Environments', value: 'local, stage, prod' },
            { label: 'Admin roles', value: 'admin, sre' },
            { label: 'Operator roles', value: 'admin, sre, operator' },
          ].map(({ label, value }) => (
            <div key={label} className="flex items-center justify-between py-2 border-b border-zinc-800/60 last:border-0">
              <span className="text-xs text-zinc-500">{label}</span>
              <code className="text-xs text-zinc-400">{value}</code>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

export default function Settings() {
  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Settings"
        subtitle="Runtime configuration, policy, thresholds, and control plane"
      />
      <div className="p-6">
        <Tabs
          tabs={[
            { key: 'general', label: 'General' },
            { key: 'policy', label: 'Policy & Actions' },
            { key: 'thresholds', label: 'Thresholds' },
            { key: 'control_plane', label: 'Control Plane' },
          ]}
        >
          {(tab) => (
            <>
              {tab === 'general' && <GeneralTab />}
              {tab === 'policy' && <PolicyTab />}
              {tab === 'thresholds' && <ThresholdsTab />}
              {tab === 'control_plane' && <ControlPlaneTab />}
            </>
          )}
        </Tabs>
      </div>
    </div>
  )
}
