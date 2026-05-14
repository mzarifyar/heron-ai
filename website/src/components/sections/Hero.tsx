'use client'

import { motion } from 'framer-motion'
import { HeronMark } from '../Logo'

const STATS = [
  { value: '< 4 min', label: 'avg auto-resolution' },
  { value: '83%',     label: 'incidents auto-healed' },
  { value: '0',       label: 'on-call wake-ups for noise' },
]

export default function Hero() {
  return (
    <section className="relative min-h-screen flex flex-col justify-center overflow-hidden grid-bg">

      {/* Ambient background glows */}
      <div className="absolute inset-0 pointer-events-none">
        <div
          className="absolute top-[-20%] left-[30%] w-[600px] h-[600px] rounded-full opacity-20"
          style={{
            background: 'radial-gradient(circle, #8b5cf6 0%, transparent 70%)',
            animation: 'heroGlow 8s ease-in-out infinite',
          }}
        />
        <div
          className="absolute top-[10%] right-[20%] w-[400px] h-[400px] rounded-full opacity-10"
          style={{
            background: 'radial-gradient(circle, #06b6d4 0%, transparent 70%)',
            animation: 'heroGlow 10s ease-in-out infinite reverse',
          }}
        />
        <div
          className="absolute bottom-[10%] left-[10%] w-[300px] h-[300px] rounded-full opacity-8"
          style={{
            background: 'radial-gradient(circle, #a78bfa 0%, transparent 70%)',
            animation: 'heroGlow 12s ease-in-out infinite',
          }}
        />
      </div>

      {/* Floating logo */}
      <div className="absolute right-[6%] top-[16%] opacity-[0.18] hidden lg:block" style={{ animation: 'float 8s ease-in-out infinite' }}>
        <img src="/logo.png" alt="" aria-hidden="true" style={{ width: 260, borderRadius: 16, objectFit: 'cover' }} />
      </div>

      <div className="relative max-w-7xl mx-auto px-6 pt-32 pb-24">
        {/* Badge */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 text-xs font-medium text-violet-300 mb-8"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
          Now in early access
        </motion.div>

        {/* Headline */}
        <motion.h1
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.1 }}
          className="text-6xl md:text-7xl lg:text-8xl font-black tracking-tight leading-[0.9] mb-8"
        >
          <span className="text-zinc-100">The loop</span>
          <br />
          <span className="shimmer-text">closes itself.</span>
        </motion.h1>

        {/* Subheadline */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.25 }}
          className="text-xl md:text-2xl text-zinc-400 max-w-2xl leading-relaxed mb-12"
        >
          Heron watches your infrastructure, detects what matters, and acts — before your phone rings.
          Every incident makes it smarter.
        </motion.p>

        {/* CTAs */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.4 }}
          className="flex flex-wrap gap-4 mb-20"
        >
          <a
            href="#access"
            className="btn-primary group inline-flex items-center gap-2 px-6 py-3.5 rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-semibold text-sm transition-all duration-200 shadow-lg shadow-violet-900/40"
          >
            Request early access
            <svg className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 8l4 4m0 0l-4 4m4-4H3" />
            </svg>
          </a>
          <a
            href="#access"
            className="inline-flex items-center gap-2 px-6 py-3.5 rounded-xl border border-zinc-700 hover:border-violet-500/50 text-zinc-300 hover:text-zinc-100 font-semibold text-sm transition-all duration-200"
          >
            Book a demo
          </a>
          <a
            href="#access"
            className="inline-flex items-center gap-2 px-6 py-3.5 rounded-xl text-zinc-500 hover:text-zinc-300 font-medium text-sm transition-colors"
          >
            Join the waitlist →
          </a>
        </motion.div>

        {/* Stats row */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.6 }}
          className="flex flex-wrap gap-8 md:gap-16"
        >
          {STATS.map((s, i) => (
            <div key={i}>
              <div className="text-3xl font-black gradient-text">{s.value}</div>
              <div className="text-sm text-zinc-500 mt-0.5">{s.label}</div>
            </div>
          ))}
        </motion.div>
      </div>

      {/* Bottom fade */}
      <div className="absolute bottom-0 inset-x-0 h-32 pointer-events-none"
        style={{ background: 'linear-gradient(to bottom, transparent, #09090b)' }} />
    </section>
  )
}
