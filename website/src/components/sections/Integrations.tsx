'use client'

import { motion, useInView } from 'framer-motion'
import { useRef } from 'react'

// SVG logos as inline components — no external images needed
const INTEGRATIONS = [
  {
    name: 'Kubernetes',
    logo: (
      <svg viewBox="0 0 24 24" className="w-7 h-7" fill="currentColor">
        <path d="M10.204 14.35l.007.01-.999 2.413a5.171 5.171 0 01-2.075-2.597l2.578-.437.004.005a.44.44 0 01.485.606zm-.833-2.129a.44.44 0 01.173-.756l.005-.002V9.16a5.207 5.207 0 00-2.894 2.047l2.716.014zm4.655-.756a.44.44 0 01.173.756l2.719-.014a5.207 5.207 0 00-2.897-2.047v2.303l.005.002zm-1.248-1.667a.44.44 0 01.482-.606l.004-.005 2.578.437a5.171 5.171 0 01-2.075 2.597l-.999-2.413.01-.01zM12 7.677a.44.44 0 01.44.44v.001l2.313.985A5.207 5.207 0 0012 7.677a5.207 5.207 0 00-2.753 1.426l2.313-.985v-.001a.44.44 0 01.44-.44zm0 .888a3.436 3.436 0 100 6.872 3.436 3.436 0 000-6.872zm6.033 3.538l-2.716.014a.44.44 0 01-.173.756l-.005.002v2.303a5.207 5.207 0 002.897-2.047l-.003-.028zm-1.038 2.49l-.007.01.999 2.413a5.171 5.171 0 002.075-2.597l-2.578-.437-.004.005a.44.44 0 01-.485-.394z"/>
        <path d="M12 1C5.925 1 1 5.925 1 12s4.925 11 11 11 11-4.925 11-11S18.075 1 12 1zm0 1.5A9.5 9.5 0 0121.5 12 9.5 9.5 0 0112 21.5 9.5 9.5 0 012.5 12 9.5 9.5 0 0112 2.5z"/>
      </svg>
    ),
    status: 'native',
  },
  {
    name: 'Jira',
    logo: (
      <svg viewBox="0 0 24 24" className="w-7 h-7" fill="currentColor">
        <path d="M11.75 0C5.373 0 0 5.373 0 11.75s5.373 11.75 11.75 11.75S23.5 18.127 23.5 11.75 18.127 0 11.75 0zm5.94 12.896l-5.453 5.453a.69.69 0 01-.974 0L5.81 12.896a.69.69 0 010-.974l5.453-5.453a.69.69 0 01.974 0l5.453 5.453a.69.69 0 010 .974z"/>
      </svg>
    ),
    status: 'native',
  },
  {
    name: 'PagerDuty',
    logo: (
      <svg viewBox="0 0 24 24" className="w-7 h-7" fill="currentColor">
        <path d="M16.003 0h-4.59l-7.415 14.226h4.59L16.003 0zm2.004 24H6.998V15.4h11.01V24zM16.003 0H6.998v9.25h9.005V0z"/>
      </svg>
    ),
    status: 'native',
  },
  {
    name: 'Slack',
    logo: (
      <svg viewBox="0 0 24 24" className="w-7 h-7" fill="currentColor">
        <path d="M5.042 15.165a2.528 2.528 0 01-2.52 2.523A2.528 2.528 0 010 15.165a2.527 2.527 0 012.522-2.52h2.52v2.52zm1.271 0a2.527 2.527 0 012.521-2.52 2.527 2.527 0 012.521 2.52v6.313A2.528 2.528 0 018.834 24a2.528 2.528 0 01-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 01-2.521-2.52A2.528 2.528 0 018.834 0a2.528 2.528 0 012.521 2.522v2.52H8.834zm0 1.27a2.528 2.528 0 012.521 2.521 2.528 2.528 0 01-2.521 2.521H2.522A2.528 2.528 0 010 8.833a2.528 2.528 0 012.522-2.521h6.312zm10.122 2.521a2.528 2.528 0 012.522-2.521A2.528 2.528 0 0124 8.833a2.528 2.528 0 01-2.522 2.521h-2.522V8.833zm-1.268 0a2.528 2.528 0 01-2.523 2.521 2.527 2.527 0 01-2.52-2.521V2.522A2.527 2.527 0 0115.165 0a2.528 2.528 0 012.523 2.522v6.311zm-2.523 10.122a2.528 2.528 0 012.523 2.522A2.528 2.528 0 0115.165 24a2.527 2.527 0 01-2.52-2.522v-2.522h2.52zm0-1.268a2.527 2.527 0 01-2.52-2.523 2.526 2.526 0 012.52-2.52h6.313A2.527 2.527 0 0124 15.165a2.528 2.528 0 01-2.522 2.523h-6.313z"/>
      </svg>
    ),
    status: 'native',
  },
  {
    name: 'Prometheus',
    logo: (
      <svg viewBox="0 0 24 24" className="w-7 h-7" fill="currentColor">
        <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm0 2c5.523 0 10 4.477 10 10s-4.477 10-10 10S2 17.523 2 12 6.477 2 12 2zm0 2.5a7.5 7.5 0 100 15 7.5 7.5 0 000-15zm0 2a5.5 5.5 0 110 11 5.5 5.5 0 010-11z"/>
      </svg>
    ),
    status: 'native',
  },
  {
    name: 'Datadog',
    logo: (
      <svg viewBox="0 0 24 24" className="w-7 h-7" fill="currentColor">
        <path d="M22.083 11.258l-1.806-.686-1.52 1.016-1.17-1.296-.002-.002-.977.593-1.52-1.016-1.806.686.001 3.484 8.8.003v-2.782zm-10.167 0l-1.806-.686-1.52 1.016-1.17-1.296-.002-.002-.977.593-1.52-1.016L3.11 11.573v.002L3.109 14.06l8.806-.001-.001-2.8z"/>
      </svg>
    ),
    status: 'coming',
  },
  {
    name: 'CloudWatch',
    logo: (
      <svg viewBox="0 0 24 24" className="w-7 h-7" fill="currentColor">
        <path d="M12 0C5.383 0 0 5.383 0 12s5.383 12 12 12 12-5.383 12-12S18.617 0 12 0zm0 21.6c-5.292 0-9.6-4.308-9.6-9.6S6.708 2.4 12 2.4s9.6 4.308 9.6 9.6-4.308 9.6-9.6 9.6z"/>
        <circle cx="12" cy="12" r="3.6"/>
      </svg>
    ),
    status: 'coming',
  },
  {
    name: 'GitHub',
    logo: (
      <svg viewBox="0 0 24 24" className="w-7 h-7" fill="currentColor">
        <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/>
      </svg>
    ),
    status: 'coming',
  },
]

export default function Integrations() {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-80px' })

  return (
    <section id="integrations" className="py-32" ref={ref}>
      <div className="max-w-7xl mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7 }}
          className="text-center mb-16"
        >
          <p className="text-sm font-mono text-violet-400 tracking-widest uppercase mb-4">Integrations</p>
          <h2 className="text-5xl font-black tracking-tight text-zinc-100 mb-4">
            Plugs into the{' '}
            <span className="gradient-text">stack you already run.</span>
          </h2>
          <p className="text-zinc-400 max-w-xl mx-auto">
            Heron connects to your existing tools in minutes. No agent. No vendor lock-in.
          </p>
        </motion.div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {INTEGRATIONS.map((intg, i) => (
            <motion.div
              key={intg.name}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={inView ? { opacity: 1, scale: 1 } : {}}
              transition={{ duration: 0.4, delay: 0.06 * i }}
              className={`glass rounded-xl p-6 flex flex-col items-center gap-3 group transition-all duration-200 hover:border-violet-500/40 hover:bg-violet-500/5 ${intg.status === 'coming' ? 'opacity-50' : ''}`}
            >
              <div className="text-zinc-400 group-hover:text-violet-400 transition-colors">
                {intg.logo}
              </div>
              <div className="text-center">
                <div className="text-sm font-medium text-zinc-300">{intg.name}</div>
                {intg.status === 'coming' && (
                  <div className="text-[10px] text-zinc-600 mt-0.5">coming soon</div>
                )}
              </div>
            </motion.div>
          ))}
        </div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={inView ? { opacity: 1 } : {}}
          transition={{ delay: 0.8 }}
          className="text-center text-sm text-zinc-600 mt-8"
        >
          More integrations via the open AlertSource adapter API.{' '}
          <a href="#access" className="text-violet-500 hover:text-violet-400 transition-colors">
            Request an integration →
          </a>
        </motion.p>
      </div>
    </section>
  )
}
