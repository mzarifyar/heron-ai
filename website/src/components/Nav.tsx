'use client'

import { useState, useEffect } from 'react'
import Logo from './Logo'

const LINKS = [
  { href: '#problem',      label: 'The Problem' },
  { href: '#how',          label: 'How It Works' },
  { href: '#chronicle',    label: 'Chronicle' },
  { href: '#integrations', label: 'Integrations' },
  { href: '#origin',       label: 'Our Name' },
]

export default function Nav() {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <nav
      className={`fixed top-0 inset-x-0 z-50 transition-all duration-300 ${
        scrolled ? 'border-b border-zinc-800/60 backdrop-blur-xl bg-zinc-950/80' : ''
      }`}
    >
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <a href="#" aria-label="Heron home">
          <Logo size={32} />
        </a>

        {/* Desktop nav */}
        <ul className="hidden md:flex items-center gap-8">
          {LINKS.map(l => (
            <li key={l.href}>
              <a
                href={l.href}
                className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors"
              >
                {l.label}
              </a>
            </li>
          ))}
        </ul>

        <div className="hidden md:flex items-center gap-3">
          <a
            href="#access"
            className="text-sm font-medium px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white transition-colors"
          >
            Get early access
          </a>
        </div>

        {/* Mobile hamburger */}
        <button
          className="md:hidden text-zinc-400 hover:text-zinc-100"
          onClick={() => setOpen(!open)}
          aria-label="Toggle menu"
        >
          <svg width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
            {open ? (
              <>
                <line x1="4" y1="4" x2="18" y2="18" /><line x1="18" y1="4" x2="4" y2="18" />
              </>
            ) : (
              <>
                <line x1="3" y1="6"  x2="19" y2="6"  />
                <line x1="3" y1="12" x2="19" y2="12" />
                <line x1="3" y1="18" x2="19" y2="18" />
              </>
            )}
          </svg>
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="md:hidden border-t border-zinc-800 bg-zinc-950/95 backdrop-blur-xl px-6 py-4 flex flex-col gap-4">
          {LINKS.map(l => (
            <a
              key={l.href}
              href={l.href}
              className="text-sm text-zinc-400 hover:text-zinc-100"
              onClick={() => setOpen(false)}
            >
              {l.label}
            </a>
          ))}
          <a
            href="#access"
            className="text-sm font-medium px-4 py-2 rounded-lg bg-violet-600 text-white text-center"
            onClick={() => setOpen(false)}
          >
            Get early access
          </a>
        </div>
      )}
    </nav>
  )
}
