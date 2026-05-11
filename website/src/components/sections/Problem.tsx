'use client'

import { motion } from 'framer-motion'
import { useInView } from 'framer-motion'
import { useRef } from 'react'

const PAINS = [
  {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
      </svg>
    ),
    title: '847 alerts per day',
    body: 'The average SRE team receives thousands of signals hourly. Over 90% are noise. Your engineers are on-call for the 3%.',
  },
  {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    title: '52 minutes average MTTR',
    body: 'Half that time is recreation — understanding what happened, finding the runbook, remembering how it was fixed last time.',
  },
  {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.5" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
      </svg>
    ),
    title: 'Knowledge walks out the door',
    body: 'Senior engineers leave. Every workaround, every known failure mode, every hard-won fix — gone. Your team starts from zero.',
  },
]

export default function Problem() {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-100px' })

  return (
    <section id="problem" className="py-32 relative" ref={ref}>
      <div className="max-w-7xl mx-auto px-6">

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7 }}
          className="max-w-2xl mb-20"
        >
          <p className="text-sm font-mono text-violet-400 tracking-widest uppercase mb-4">The problem</p>
          <h2 className="text-5xl md:text-6xl font-black tracking-tight leading-tight mb-6">
            <span className="text-zinc-100">It's 3 AM.</span>
            <br />
            <span className="text-zinc-500">Your phone rings. Again.</span>
          </h2>
          <p className="text-lg text-zinc-400 leading-relaxed">
            Modern infrastructure is too complex and too fast for humans to watch alone.
            The on-call rotation is burning out your best engineers — not because they can&apos;t handle
            real incidents, but because 90% of what wakes them up shouldn&apos;t.
          </p>
        </motion.div>

        <div className="grid md:grid-cols-3 gap-6">
          {PAINS.map((p, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 40 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.6, delay: 0.15 * i }}
              className="glass rounded-2xl p-8 group hover:border-violet-500/40 transition-colors"
            >
              <div className="w-10 h-10 rounded-xl bg-violet-500/15 flex items-center justify-center text-violet-400 mb-6 group-hover:bg-violet-500/25 transition-colors">
                {p.icon}
              </div>
              <h3 className="text-xl font-bold text-zinc-100 mb-3">{p.title}</h3>
              <p className="text-zinc-400 leading-relaxed">{p.body}</p>
            </motion.div>
          ))}
        </div>

        {/* Divider quote */}
        <motion.blockquote
          initial={{ opacity: 0 }}
          animate={inView ? { opacity: 1 } : {}}
          transition={{ duration: 0.8, delay: 0.6 }}
          className="mt-24 text-center max-w-3xl mx-auto"
        >
          <p className="text-2xl md:text-3xl font-semibold text-zinc-300 leading-relaxed">
            &ldquo;MTTR stays high not because engineers lack skill —
            but because{' '}
            <span className="gradient-text">institutional knowledge doesn&apos;t compound.</span>
            &rdquo;
          </p>
        </motion.blockquote>
      </div>
    </section>
  )
}
