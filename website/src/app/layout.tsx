import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Heron — Autonomous Incident Intelligence',
  description: 'Heron watches your infrastructure, detects what matters, and acts — before your phone rings. Every incident makes it smarter.',
  metadataBase: new URL('https://heron-ai.net'),
  openGraph: {
    title: 'Heron — The loop closes itself.',
    description: 'Autonomous incident intelligence for SRE and DevOps teams.',
    type: 'website',
    url: 'https://heron-ai.net',
    siteName: 'Heron',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Heron — The loop closes itself.',
    description: 'Autonomous incident intelligence for SRE and DevOps teams.',
  },
  alternates: {
    canonical: 'https://heron-ai.net',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark scroll-smooth">
      <body>{children}</body>
    </html>
  )
}
