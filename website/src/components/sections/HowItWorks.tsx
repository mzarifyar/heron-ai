'use client'

import { motion, useInView } from 'framer-motion'
import { useRef } from 'react'

const STEPS = [
  {
    n: '01',
    title: 'Connect your stack',
    body: 'Point Heron at your Kubernetes clusters, alert manager, Jira, and Slack. Five minutes to first signal ingested.',
    tag: 'Setup',
    color: '#8b5cf6',
  },
  {
    n: '02',
    title: 'Heron watches everything',
    body: 'Signals stream in from every source. Noise is filtered. Anomalies are correlated. Patterns are matched against Chronicle history.',
    tag: 'Observe + Detect',
    color: '#7c3aed',
  },
  {
    n: '03',
    title: 'The loop runs autonomously',
    body: 'For known patterns, Heron decides, acts, and verifies without human input. For novel incidents, it escalates with full context.',
    tag: 'Decide + Act + Verify',
    color: '#0891b2',
  },
  {
    n: '04',
    title: 'Chronicle remembers',
    body: 'Every outcome — success, failure, near-miss — is recorded. Confidence scores update. Next time is faster.',
    tag: 'Learn',
    color: '#06b6d4',
  },
]

export default function HowItWorks() {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-80px' })

  return (
    <section id="how" className="py-32" ref={ref}>
      <div className="max-w-7xl mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7 }}
          className="text-center mb-20"
        >
          <p className="text-sm font-mono text-violet-400 tracking-widest uppercase mb-4">How it works</p>
          <h2 className="text-5xl md:text-6xl font-black tracking-tight text-zinc-100">
            Four steps to{' '}
            <span className="gradient-text">autonomous ops.</span>
          </h2>
        </motion.div>

        {/* Steps */}
        <div className="relative">
          {/* Connecting line */}
          <div className="absolute left-[30px] md:left-1/2 top-0 bottom-0 w-px bg-gradient-to-b from-violet-500/50 via-cyan-500/30 to-transparent hidden md:block" style={{ transform: 'translateX(-50%)' }} />

          <div className="space-y-12">
            {STEPS.map((s, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 40 }}
                animate={inView ? { opacity: 1, y: 0 } : {}}
                transition={{ duration: 0.6, delay: 0.15 * i }}
                className={`flex flex-col md:flex-row gap-8 items-center ${i % 2 === 1 ? 'md:flex-row-reverse' : ''}`}
              >
                {/* Content card */}
                <div className="flex-1 glass rounded-2xl p-8 group hover:border-violet-500/30 transition-all duration-300">
                  <div className="flex items-center gap-3 mb-4">
                    <span className="text-xs font-mono px-2 py-1 rounded-full border"
                      style={{ borderColor: s.color + '40', color: s.color, background: s.color + '10' }}>
                      {s.tag}
                    </span>
                  </div>
                  <h3 className="text-2xl font-bold text-zinc-100 mb-3">{s.title}</h3>
                  <p className="text-zinc-400 leading-relaxed">{s.body}</p>
                </div>

                {/* Step number node — sits on the center line */}
                <div className="shrink-0 flex items-center justify-center w-16 h-16 rounded-full border-2 font-black text-xl z-10"
                  style={{
                    borderColor: s.color,
                    background: s.color + '15',
                    color: s.color,
                    boxShadow: `0 0 24px ${s.color}30`,
                  }}>
                  {s.n}
                </div>

                {/* Empty spacer for alternating layout */}
                <div className="flex-1 hidden md:block" />
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
