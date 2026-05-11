import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import GoldenSignals from './pages/GoldenSignals'
import Incidents from './pages/Incidents'
import IncidentDetail from './pages/IncidentDetail'
import Intelligence from './pages/Intelligence'
import Integrations from './pages/Integrations'
import Infrastructure from './pages/Infrastructure'
import ServiceMap from './pages/ServiceMap'
import Settings from './pages/Settings'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/golden-signals" element={<GoldenSignals />} />
        <Route path="/incidents" element={<Incidents />} />
        <Route path="/incidents/:id" element={<IncidentDetail />} />
        <Route path="/intelligence" element={<Intelligence />} />
        <Route path="/integrations" element={<Integrations />} />
        <Route path="/infrastructure" element={<Infrastructure />} />
        <Route path="/service-map" element={<ServiceMap />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Layout>
  )
}
