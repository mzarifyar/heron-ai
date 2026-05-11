'use client'

import { motion, useInView } from 'framer-motion'
import { useRef, useState } from 'react'

type Tab = 'access' | 'demo' | 'waitlist'

const TABS: { id: Tab; label: string; desc: string; btn: string }[] = [
  {
    id: 'access',
    label: 'Early Access',
    desc: 'Get production access before public launch. We onboard 10 teams per month.',
    btn: 'Request early access',
  },
  {
    id: 'demo',
    label: 'Book a Demo',
    desc: 'A 30-minute live walkthrough of Heron with your team. We bring the data.',
    btn: 'Book a demo',
  },
  {
    id: 'waitlist',
    label: 'Join the Waitlist',
    desc: "Not ready yet? Get on the list and we'll notify you when a slot opens.",
    btn: 'Join waitlist',
  },
]

function Form({ type }: { type: Tab }) {
  const [email,    setEmail]    = useState('')
  const [company,  setCompany]  = useState('')
  const [teamSize, setTeamSize] = useState('')
  const [loading,  setLoading]  = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error,    setError]    = useState('')

  const handle = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email) return
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/waitlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, company, team_size: teamSize, type }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error ?? `HTTP ${res.status}`)
      }
      setSubmitted(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (submitted) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="text-center py-8"
      >
        <div className="w-12 h-12 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center mx-auto mb-4">
          <svg className="w-6 h-6 text-emerald-400" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <p className="text-zinc-100 font-semibold text-lg mb-2">You&apos;re in.</p>
        <p className="text-zinc-400 text-sm">
          We&apos;ll be in touch at <strong className="text-zinc-300">{email}</strong> within 24 hours.
        </p>
      </motion.div>
    )
  }

  return (
    <form onSubmit={handle} className="space-y-4">
      <div className="grid sm:grid-cols-2 gap-4">
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="you@company.com"
          required
          className="w-full px-4 py-3 rounded-xl bg-zinc-800/80 border border-zinc-700 text-zinc-100 placeholder:text-zinc-600 text-sm focus:outline-none focus:border-violet-500 transition-colors"
        />
        <input
          type="text"
          value={company}
          onChange={e => setCompany(e.target.value)}
          placeholder="Company name"
          className="w-full px-4 py-3 rounded-xl bg-zinc-800/80 border border-zinc-700 text-zinc-100 placeholder:text-zinc-600 text-sm focus:outline-none focus:border-violet-500 transition-colors"
        />
      </div>
      {type === 'demo' && (
        <select
          value={teamSize}
          onChange={e => setTeamSize(e.target.value)}
          className="w-full px-4 py-3 rounded-xl bg-zinc-800/80 border border-zinc-700 text-zinc-400 text-sm focus:outline-none focus:border-violet-500 transition-colors"
        >
          <option value="">Team size</option>
          <option>1–10 engineers</option>
          <option>10–50 engineers</option>
          <option>50–200 engineers</option>
          <option>200+ engineers</option>
        </select>
      )}
      {error && (
        <p className="text-xs text-rose-400 text-center">{error}</p>
      )}
      <button
        type="submit"
        disabled={loading}
        className="w-full py-3.5 rounded-xl font-semibold text-sm text-white transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        style={{ background: 'linear-gradient(135deg, #7c3aed, #0e7490)' }}
      >
        {loading && (
          <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
        )}
        {loading ? 'Submitting…' : TABS.find(t => t.id === type)?.btn}
      </button>
      <p className="text-xs text-zinc-600 text-center">No credit card. No commitment.</p>
    </form>
  )
}

export default function CTA() {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-80px' })
  const [active, setActive] = useState<Tab>('access')
  const tab = TABS.find(t => t.id === active)!

  return (
    <section id="access" className="py-32 relative" ref={ref}>
      {/* Ambient glow */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full opacity-10"
          style={{ background: 'radial-gradient(circle, #8b5cf6, transparent 70%)' }} />
      </div>

      <div className="relative max-w-3xl mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7 }}
          className="text-center mb-12"
        >
          <p className="text-sm font-mono text-violet-400 tracking-widest uppercase mb-4">Get started</p>
          <h2 className="text-5xl md:text-6xl font-black tracking-tight">
            <span className="text-zinc-100">Stop watching.</span>
            <br />
            <span className="gradient-text">Let Heron watch.</span>
          </h2>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7, delay: 0.2 }}
          className="glass rounded-2xl overflow-hidden"
        >
          {/* Tab headers */}
          <div className="flex border-b border-zinc-800">
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setActive(t.id)}
                className={`flex-1 py-4 text-sm font-medium transition-colors ${
                  active === t.id
                    ? 'text-violet-400 border-b-2 border-violet-500 -mb-px'
                    : 'text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Form body */}
          <div className="p-8">
            <p className="text-zinc-400 text-sm mb-6">{tab.desc}</p>
            <Form key={active} type={active} />
          </div>
        </motion.div>
      </div>
    </section>
  )
}
