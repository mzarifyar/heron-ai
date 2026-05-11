'use client'

import { motion, useInView } from 'framer-motion'
import { useRef } from 'react'

const NODES = [
  { id: 'observe',  label: 'Observe',  angle: -90,  color: '#8b5cf6', desc: 'Every signal ingested and normalised in real time' },
  { id: 'detect',   label: 'Detect',   angle: -38,  color: '#7c3aed', desc: 'Anomalies surfaced, alert noise filtered' },
  { id: 'decide',   label: 'Decide',   angle: 14,   color: '#6d28d9', desc: 'AI selects the highest-confidence remediation' },
  { id: 'act',      label: 'Act',      angle: 66,   color: '#0e7490', desc: 'Approved action executed autonomously' },
  { id: 'verify',   label: 'Verify',   angle: 118,  color: '#0891b2', desc: 'Outcome confirmed before closing' },
  { id: 'escalate', label: 'Escalate', angle: 170,  color: '#06b6d4', desc: 'Human loop-in when confidence is low' },
  { id: 'learn',    label: 'Learn',    angle: -142, color: '#a78bfa', desc: 'Every outcome recorded in Chronicle' },
]

const R = 130  // circle radius
const CX = 160 // center x
const CY = 160 // center y

function toXY(angleDeg: number, r: number) {
  const rad = (angleDeg * Math.PI) / 180
  return { x: CX + r * Math.cos(rad), y: CY + r * Math.sin(rad) }
}

export default function TheLoop() {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-80px' })

  return (
    <section id="loop" className="py-32 relative overflow-hidden">
      {/* Background gradient */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute inset-0"
          style={{ background: 'radial-gradient(ellipse 60% 60% at 50% 50%, rgba(139,92,246,0.06), transparent)' }} />
      </div>

      <div className="max-w-7xl mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7 }}
          ref={ref}
          className="text-center mb-20"
        >
          <p className="text-sm font-mono text-violet-400 tracking-widest uppercase mb-4">The closed loop</p>
          <h2 className="text-5xl md:text-6xl font-black tracking-tight text-zinc-100 mb-6">
            Seven steps.{' '}
            <span className="gradient-text">No humans required.</span>
          </h2>
          <p className="text-lg text-zinc-400 max-w-2xl mx-auto leading-relaxed">
            Heron runs a continuous autonomous loop around your infrastructure.
            Most incidents close before anyone is paged.
          </p>
        </motion.div>

        <div className="flex flex-col lg:flex-row items-center gap-16 lg:gap-24">
          {/* Animated SVG loop diagram */}
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={inView ? { opacity: 1, scale: 1 } : {}}
            transition={{ duration: 0.8, delay: 0.2 }}
            className="shrink-0 flex items-center justify-center"
          >
            <svg
              width="320"
              height="320"
              viewBox="0 0 320 320"
              className="overflow-visible"
            >
              <defs>
                {NODES.map(n => (
                  <radialGradient key={n.id} id={`ng-${n.id}`} cx="50%" cy="50%" r="50%">
                    <stop offset="0%"   stopColor={n.color} stopOpacity="0.9" />
                    <stop offset="100%" stopColor={n.color} stopOpacity="0.3" />
                  </radialGradient>
                ))}
                <linearGradient id="arcGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%"   stopColor="#8b5cf6" />
                  <stop offset="100%" stopColor="#06b6d4" />
                </linearGradient>
              </defs>

              {/* Orbit ring */}
              <circle
                cx={CX} cy={CY} r={R}
                stroke="rgba(139,92,246,0.12)"
                strokeWidth="1"
                fill="none"
                strokeDasharray="4 4"
              />

              {/* Animated arc — full ring highlight */}
              <circle
                cx={CX} cy={CY} r={R}
                stroke="url(#arcGrad)"
                strokeWidth="2"
                fill="none"
                strokeDasharray={`${2 * Math.PI * R}`}
                strokeDashoffset={`${2 * Math.PI * R * 0.6}`}
                strokeLinecap="round"
                style={{
                  animation: 'spin 12s linear infinite',
                  transformOrigin: `${CX}px ${CY}px`,
                  opacity: 0.5,
                }}
              />

              {/* Nodes */}
              {NODES.map((n, i) => {
                const pos = toXY(n.angle, R)
                const delay = `${i * 1.0}s`
                return (
                  <g key={n.id}>
                    {/* Outer glow ring */}
                    <circle
                      cx={pos.x} cy={pos.y} r="22"
                      fill="none"
                      stroke={n.color}
                      strokeWidth="1"
                      opacity="0.2"
                      style={{
                        animation: `nodeActivate 7s ${delay} ease-in-out infinite`,
                      }}
                    />
                    {/* Node circle */}
                    <circle
                      cx={pos.x} cy={pos.y} r="16"
                      fill={`url(#ng-${n.id})`}
                      style={{
                        animation: `nodeActivate 7s ${delay} ease-in-out infinite`,
                      }}
                    />
                    {/* Node border */}
                    <circle
                      cx={pos.x} cy={pos.y} r="16"
                      fill="none"
                      stroke={n.color}
                      strokeWidth="1.5"
                      opacity="0.6"
                    />
                    {/* Label */}
                    <text
                      x={pos.x}
                      y={pos.y + (n.angle > 0 && n.angle < 180 ? 34 : -24)}
                      textAnchor="middle"
                      className="font-sans"
                      style={{
                        fontSize: '11px',
                        fill: '#a1a1aa',
                        fontWeight: 600,
                        fontFamily: 'Inter, sans-serif',
                        letterSpacing: '0.05em',
                      }}
                    >
                      {n.label.toUpperCase()}
                    </text>
                    {/* Step number inside node */}
                    <text
                      x={pos.x}
                      y={pos.y + 4.5}
                      textAnchor="middle"
                      style={{
                        fontSize: '11px',
                        fill: 'white',
                        fontWeight: 700,
                        fontFamily: 'Inter, sans-serif',
                      }}
                    >
                      {i + 1}
                    </text>
                  </g>
                )
              })}

              {/* Center label */}
              <text x={CX} y={CY - 10} textAnchor="middle"
                style={{ fontSize: '13px', fill: '#71717a', fontFamily: 'Inter, sans-serif', fontWeight: 500 }}>
                autonomous
              </text>
              <text x={CX} y={CY + 8} textAnchor="middle"
                style={{ fontSize: '13px', fill: '#71717a', fontFamily: 'Inter, sans-serif', fontWeight: 500 }}>
                loop
              </text>
            </svg>
          </motion.div>

          {/* Step descriptions */}
          <div className="flex-1 grid sm:grid-cols-2 gap-4">
            {NODES.map((n, i) => (
              <motion.div
                key={n.id}
                initial={{ opacity: 0, x: 30 }}
                animate={inView ? { opacity: 1, x: 0 } : {}}
                transition={{ duration: 0.5, delay: 0.1 * i + 0.4 }}
                className="glass rounded-xl p-5 group hover:border-violet-500/30 transition-colors"
              >
                <div className="flex items-center gap-3 mb-2">
                  <span
                    className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white"
                    style={{ background: n.color }}
                  >
                    {i + 1}
                  </span>
                  <span className="text-sm font-semibold text-zinc-100">{n.label}</span>
                </div>
                <p className="text-xs text-zinc-500 leading-relaxed pl-9">{n.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
