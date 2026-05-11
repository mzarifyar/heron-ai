import Logo from './Logo'

const LINKS: Record<string, { label: string; href: string }[]> = {
  Product: [
    { label: 'How It Works',  href: '#how' },
    { label: 'Chronicle',     href: '#chronicle' },
    { label: 'Integrations',  href: '#integrations' },
    { label: 'Early Access',  href: '#access' },
    { label: 'GitHub',        href: 'https://github.com/mzarifyar/heron-ai' },
  ],
  Company: [
    { label: 'Our Name',      href: '#origin' },
    { label: 'The Problem',   href: '#problem' },
    { label: 'Get a Demo',    href: '#access' },
    { label: 'Join Waitlist', href: '#access' },
  ],
  Legal: [
    { label: 'MIT License',   href: 'https://github.com/mzarifyar/heron-ai/blob/main/LICENSE' },
    { label: 'GitHub',        href: 'https://github.com/mzarifyar/heron-ai' },
    { label: 'Contact',       href: '#access' },
  ],
}

export default function Footer() {
  return (
    <footer className="border-t border-zinc-800/60 py-16">
      <div className="max-w-7xl mx-auto px-6">
        <div className="flex flex-col md:flex-row gap-12 md:gap-24 mb-12">
          <div className="md:w-1/3">
            <Logo size={32} className="mb-4" />
            <p className="text-sm text-zinc-500 leading-relaxed max-w-xs">
              Autonomous incident intelligence for SRE and DevOps teams.
              The loop closes itself.
            </p>
            <p className="text-xs text-zinc-700 mt-4 font-mono">
              Named after Heron of Alexandria<br />c. 10–70 AD
            </p>
          </div>

          <div className="flex-1 grid grid-cols-3 gap-8">
            {Object.entries(LINKS).map(([group, items]) => (
              <div key={group}>
                <h4 className="text-xs font-semibold text-zinc-500 uppercase tracking-widest mb-4">
                  {group}
                </h4>
                <ul className="space-y-2.5">
                  {items.map(item => (
                    <li key={item.label}>
                      <a
                        href={item.href}
                        target={item.href.startsWith('http') ? '_blank' : undefined}
                        rel={item.href.startsWith('http') ? 'noreferrer' : undefined}
                        className="text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
                      >
                        {item.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-center justify-between pt-8 border-t border-zinc-800/40 gap-4">
          <p className="text-xs text-zinc-600">
            © 2026 Heron. MIT License. Copyright Mostafa Zarifyar.
          </p>
          <div className="flex items-center gap-6">
            <a href="https://github.com/mzarifyar/heron-ai" target="_blank" rel="noreferrer"
              className="text-zinc-600 hover:text-zinc-400 transition-colors text-xs font-mono">
              github.com/mzarifyar/heron-ai
            </a>
          </div>
        </div>
      </div>
    </footer>
  )
}
