'use client'

import { motion, useInView } from 'framer-motion'
import { useRef, useEffect, useState } from 'react'

function Counter({ end, suffix = '' }: { end: number; suffix?: string }) {
  const [count, setCount] = useState(0)
  const ref = useRef(null)
  const inView = useInView(ref, { once: true })

  useEffect(() => {
    if (!inView) return
    let frame = 0
    const total = 60
    const timer = setInterval(() => {
      frame++
      setCount(Math.round((frame / total) * end))
      if (frame >= total) clearInterval(timer)
    }, 20)
    return () => clearInterval(timer)
  }, [inView, end])

  return <span ref={ref}>{count.toLocaleString()}{suffix}</span>
}

const FEATURES = [
  {
    title: 'Every incident, fully indexed',
    body: 'Timeline, signals, decisions, actions, outcomes — structured and searchable the moment the loop closes.',
  },
  {
    title: 'Decisions that explain themselves',
    body: 'Heron records why it took each action. Postmortems write themselves. Audits pass themselves.',
  },
  {
    title: 'Institutional memory that compounds',
    body: 'Confidence scores improve with every resolved incident. The more Heron sees, the better it gets.',
  },
  {
    title: 'Near-miss detection',
    body: 'Chronicle flags incidents that almost happened. Fix the conditions before the breach.',
  },
]

export default function Chronicle() {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-80px' })

  return (
    <section id="chronicle" className="py-32 relative" ref={ref}>
      {/* Dark section bg */}
      <div className="absolute inset-0 bg-zinc-900/40" />

      <div className="relative max-w-7xl mx-auto px-6">
        <div className="flex flex-col lg:flex-row gap-20 items-center">

          {/* Left: Chronicle vault visualization */}
          <motion.div
            initial={{ opacity: 0, x: -40 }}
            animate={inView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.8 }}
            className="lg:w-1/2 shrink-0"
          >
            {/* Visual: stacked incident cards */}
            <div className="relative w-full max-w-md mx-auto">
              {/* Glow */}
              <div className="absolute inset-0 rounded-3xl"
                style={{ background: 'radial-gradient(ellipse 70% 50% at 50% 60%, rgba(139,92,246,0.2), transparent)' }} />

              {/* Stacked cards suggesting depth */}
              {[3, 2, 1].map(depth => (
                <div
                  key={depth}
                  className="absolute inset-0 rounded-2xl border border-violet-500/10 bg-zinc-900/60"
                  style={{
                    transform: `translateY(${depth * 6}px) scale(${1 - depth * 0.025})`,
                    zIndex: 3 - depth,
                  }}
                />
              ))}

              {/* Main card */}
              <div className="relative z-10 glass rounded-2xl p-8 border-violet-500/20">
                <div className="flex items-center justify-between mb-6">
                  <span className="text-xs font-mono text-violet-400 tracking-widest">CHRONICLE</span>
                  <span className="text-xs text-zinc-600 font-mono">v2.4.1</span>
                </div>

                {/* Fake incident entries */}
                {[
                  { id: 'INC-1847', svc: 'payment-processor', time: '3m ago',  status: 'auto-healed', sev: 'sev1' },
                  { id: 'INC-1846', svc: 'auth-service',       time: '1h ago',  status: 'resolved',   sev: 'sev2' },
                  { id: 'INC-1845', svc: 'search-service',     time: '4h ago',  status: 'resolved',   sev: 'sev3' },
                  { id: 'INC-1844', svc: 'api-gateway',        time: '12h ago', status: 'escalated',  sev: 'sev1' },
                ].map((inc, i) => (
                  <motion.div
                    key={inc.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={inView ? { opacity: 1, x: 0 } : {}}
                    transition={{ delay: 0.3 + i * 0.1 }}
                    className="flex items-center gap-3 py-2.5 border-b border-zinc-800/50 last:border-0"
                  >
                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      inc.status === 'auto-healed' ? 'bg-emerald-400' :
                      inc.status === 'escalated'   ? 'bg-amber-400'   : 'bg-zinc-500'
                    }`} />
                    <span className="text-xs font-mono text-zinc-500 shrink-0">{inc.id}</span>
                    <span className="text-xs text-zinc-300 flex-1 truncate">{inc.svc}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                      inc.sev === 'sev1' ? 'bg-rose-500/20 text-rose-400' :
                      inc.sev === 'sev2' ? 'bg-amber-500/20 text-amber-400' : 'bg-zinc-700 text-zinc-400'
                    }`}>{inc.sev}</span>
                    <span className="text-[10px] text-zinc-600">{inc.time}</span>
                  </motion.div>
                ))}

                {/* Stats row */}
                <div className="flex gap-6 mt-6 pt-4 border-t border-zinc-800/50">
                  <div>
                    <div className="text-xl font-black gradient-text">
                      <Counter end={1847} />
                    </div>
                    <div className="text-xs text-zinc-600">incidents stored</div>
                  </div>
                  <div>
                    <div className="text-xl font-black gradient-text">
                      <Counter end={94} suffix="%" />
                    </div>
                    <div className="text-xs text-zinc-600">auto-resolved</div>
                  </div>
                  <div>
                    <div className="text-xl font-black gradient-text">
                      <Counter end={3} suffix="m 47s" />
                    </div>
                    <div className="text-xs text-zinc-600">avg MTTR</div>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>

          {/* Right: Copy */}
          <div className="lg:w-1/2">
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.7 }}
            >
              <p className="text-sm font-mono text-violet-400 tracking-widest uppercase mb-4">Chronicle — The Moat</p>
              <h2 className="text-5xl font-black tracking-tight leading-tight mb-6">
                <span className="text-zinc-100">Heron never</span>
                <br />
                <span className="gradient-text">forgets.</span>
              </h2>
              <p className="text-lg text-zinc-400 leading-relaxed mb-10">
                Every incident, decision, and outcome is written to Chronicle — a structured,
                queryable knowledge base. The longer Heron runs, the more it knows.
                The more it knows, the faster it resolves. The data doesn&apos;t just accumulate.
                <strong className="text-zinc-200"> It compounds.</strong>
              </p>

              <div className="space-y-6">
                {FEATURES.map((f, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: 20 }}
                    animate={inView ? { opacity: 1, x: 0 } : {}}
                    transition={{ delay: 0.2 + i * 0.1 }}
                    className="flex gap-4"
                  >
                    <div className="w-1.5 rounded-full bg-gradient-to-b from-violet-500 to-cyan-500 shrink-0 mt-1 opacity-60" style={{ minHeight: 32 }} />
                    <div>
                      <div className="font-semibold text-zinc-100 mb-1">{f.title}</div>
                      <div className="text-zinc-500 text-sm leading-relaxed">{f.body}</div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          </div>
        </div>
      </div>
    </section>
  )
}
