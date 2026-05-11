import { useQuery } from '@tanstack/react-query'
import { Settings2, FileCode, Shield, Gauge, Server } from 'lucide-react'
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

function PolicyTab() {
  return (
    <div className="space-y-4 mt-4">
      <Card>
        <CardHeader
          title="Policy Engine"
          subtitle="Guardrail rules are declared in config/policy.yaml"
        />
        <p className="text-sm text-zinc-500 mb-4">
          Policy rules gate all automated actions. Edit{' '}
          <code className="bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-300 text-xs">
            config/policy.yaml
          </code>{' '}
          in your deployment to add or modify rules.
        </p>
        <div className="space-y-2">
          {[
            'Rate-limit: max 3 remediations per service per hour',
            'Block: no invasive actions on prod without sre role',
            'Require: verify step before escalation',
            'Allow: read-only diagnostics always permitted',
          ].map((rule) => (
            <div key={rule} className="flex items-start gap-2 text-sm">
              <Shield className="w-3.5 h-3.5 text-violet-400 mt-0.5 shrink-0" />
              <span className="text-zinc-400">{rule}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Actions Playbook"
          subtitle="Registered Reflex actions are declared in config/actions.yaml"
        />
        <p className="text-sm text-zinc-500">
          Add new actions by editing{' '}
          <code className="bg-zinc-800 px-1.5 py-0.5 rounded text-zinc-300 text-xs">
            config/actions.yaml
          </code>
          . Each action specifies a command, target selector, and policy gates.
        </p>
      </Card>
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
