'use client'

interface LogoProps {
  size?: number
  showWordmark?: boolean
  className?: string
}

export function HeronMark({ size = 40 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size * 1.25}
      viewBox="0 0 64 80"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="hg" x1="0" y1="0" x2="64" y2="80" gradientUnits="userSpaceOnUse">
          <stop offset="0%"   stopColor="#c4b5fd" />
          <stop offset="50%"  stopColor="#8b5cf6" />
          <stop offset="100%" stopColor="#06b6d4" />
        </linearGradient>
        <linearGradient id="hg2" x1="0" y1="0" x2="64" y2="80" gradientUnits="userSpaceOnUse">
          <stop offset="0%"   stopColor="#a78bfa" stopOpacity="0.6" />
          <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.4" />
        </linearGradient>
        <filter id="glow">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      {/*
        Heron silhouette — profile view, bird faces right.
        Tracing clockwise from beak tip:
        beak tip → crown → nape → down back of neck → around body/tail → up belly → up front of neck → back to beak
      */}
      <path
        d="
          M 58 10
          C 50 5, 40 5, 36 10
          C 32 14, 28 19, 22 26
          C 16 33, 10 42, 8  52
          C 6  60, 8  68, 14 72
          C 20 76, 30 76, 36 72
          C 42 68, 44 62, 40 56
          C 38 52, 34 48, 34 44
          C 34 40, 36 36, 40 32
          C 44 28, 48 23, 50 18
          C 52 14, 54 11, 58 10
          Z
        "
        fill="url(#hg)"
        filter="url(#glow)"
      />

      {/* Wing highlight — subtle secondary shape suggesting folded wing */}
      <path
        d="
          M 36 72
          C 30 76, 20 76, 14 72
          C 18 74, 28 72, 36 66
          C 38 68, 38 70, 36 72
          Z
        "
        fill="url(#hg2)"
      />

      {/* Eye — small bright dot */}
      <circle cx="48" cy="13" r="2.5" fill="white" opacity="0.9" />
      <circle cx="48" cy="13" r="1.2" fill="#09090b" />

      {/* Beak tip accent */}
      <circle cx="58" cy="10" r="1.5" fill="#22d3ee" opacity="0.8" />
    </svg>
  )
}

export function HeronWordmark({ size = 28 }: { size?: number }) {
  return (
    <span
      style={{ fontSize: size, fontWeight: 700, letterSpacing: '-0.02em', lineHeight: 1 }}
      className="gradient-text font-sans"
    >
      HERON
    </span>
  )
}

export default function Logo({ size = 36, showWordmark = true, className = '' }: LogoProps) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <img
        src="/logo.png"
        alt="Heron AI"
        style={{ height: size, width: size, borderRadius: 6, objectFit: 'cover' }}
      />
      {showWordmark && (
        <div className="flex flex-col leading-none">
          <HeronWordmark size={size * 0.7} />
          <span
            className="font-mono text-zinc-500"
            style={{ fontSize: size * 0.28, letterSpacing: '0.1em' }}
          >
            {'{ai}'}
          </span>
        </div>
      )}
    </div>
  )
}
