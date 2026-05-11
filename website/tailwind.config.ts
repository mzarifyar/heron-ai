import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      colors: {
        heron: {
          violet: '#8b5cf6',
          cyan:   '#06b6d4',
        },
      },
      backgroundImage: {
        'heron-gradient': 'linear-gradient(135deg, #8b5cf6, #06b6d4)',
        'hero-glow':      'radial-gradient(ellipse 80% 50% at 50% -20%, rgba(139,92,246,0.25), transparent)',
        'card-glow':      'radial-gradient(ellipse 60% 40% at 50% 100%, rgba(139,92,246,0.12), transparent)',
      },
      animation: {
        'gradient-shift': 'gradientShift 8s ease infinite',
        'float':          'float 6s ease-in-out infinite',
        'pulse-slow':     'pulse 4s cubic-bezier(0.4,0,0.6,1) infinite',
        'glow':           'glow 3s ease-in-out infinite',
        'spin-slow':      'spin 20s linear infinite',
      },
      keyframes: {
        gradientShift: {
          '0%,100%': { backgroundPosition: '0% 50%' },
          '50%':     { backgroundPosition: '100% 50%' },
        },
        float: {
          '0%,100%': { transform: 'translateY(0px)' },
          '50%':     { transform: 'translateY(-12px)' },
        },
        glow: {
          '0%,100%': { boxShadow: '0 0 20px rgba(139,92,246,0.3)' },
          '50%':     { boxShadow: '0 0 40px rgba(139,92,246,0.6), 0 0 80px rgba(6,182,212,0.2)' },
        },
      },
    },
  },
  plugins: [],
}

export default config
