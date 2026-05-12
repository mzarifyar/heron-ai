import { NextRequest, NextResponse } from 'next/server'
import { Resend } from 'resend'
import fs from 'fs'
import path from 'path'

const SLACK_WEBHOOK  = process.env.SLACK_WEBHOOK_URL ?? ''
const RESEND_API_KEY = process.env.RESEND_API_KEY ?? ''
const FROM_EMAIL     = process.env.WAITLIST_FROM_EMAIL ?? 'Heron <hello@heron-ai.net>'
const NOTIFY_EMAIL   = process.env.WAITLIST_NOTIFY_EMAIL ?? ''
// Local file store — used in dev / self-hosted. Skip on Vercel (ephemeral fs).
const STORE_PATH     = process.env.WAITLIST_STORE_PATH ?? ''

const TYPE_LABELS: Record<string, string> = {
  access:   '🚀 Early Access Request',
  demo:     '📅 Demo Request',
  waitlist: '📋 Waitlist Signup',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function slackText(label: string, email: string, company?: string, teamSize?: string) {
  return [
    `*${label}*`,
    `*Email:* ${email}`,
    company  ? `*Company:* ${company}`    : null,
    teamSize ? `*Team size:* ${teamSize}` : null,
    `*Time:* ${new Date().toISOString()}`,
    `*Source:* heron-ai.net`,
  ].filter(Boolean).join('\n')
}

async function notifySlack(label: string, email: string, company?: string, teamSize?: string) {
  if (!SLACK_WEBHOOK) return
  const text = slackText(label, email, company, teamSize)
  await fetch(SLACK_WEBHOOK, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text: `New ${label.toLowerCase()} from *${email}*`,
      blocks: [{ type: 'section', text: { type: 'mrkdwn', text } }, { type: 'divider' }],
    }),
  })
}

async function sendConfirmation(type: string, email: string) {
  if (!RESEND_API_KEY) return
  const resend = new Resend(RESEND_API_KEY)

  const subjects: Record<string, string> = {
    access:   "You're on the Heron early access list",
    demo:     "Your Heron demo request is confirmed",
    waitlist: "You're on the Heron waitlist",
  }
  const bodies: Record<string, string> = {
    access:   "We onboard 10 teams per month. We'll reach out within 24 hours to get you set up.",
    demo:     "We'll send you a calendar link within 24 hours to schedule your 30-minute walkthrough.",
    waitlist: "We'll notify you as soon as a slot opens. In the meantime, follow our progress at heron-ai.net.",
  }

  await resend.emails.send({
    from:    FROM_EMAIL,
    to:      email,
    subject: subjects[type] ?? "Thanks for your interest in Heron",
    html: `
      <div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;background:#09090b;color:#e4e4e7;border-radius:12px">
        <p style="font-size:22px;font-weight:700;margin:0 0 12px">You&apos;re in.</p>
        <p style="color:#a1a1aa;margin:0 0 24px;line-height:1.6">${bodies[type]}</p>
        <hr style="border:none;border-top:1px solid #27272a;margin:24px 0"/>
        <p style="color:#52525b;font-size:12px;margin:0">
          Heron — autonomous incident intelligence<br/>
          <a href="https://heron-ai.net" style="color:#7c3aed">heron-ai.net</a>
        </p>
      </div>
    `,
  })

  // Optional: BCC yourself on every submission
  if (NOTIFY_EMAIL) {
    await resend.emails.send({
      from:    FROM_EMAIL,
      to:      NOTIFY_EMAIL,
      subject: `[Heron] ${TYPE_LABELS[type] ?? 'New signup'} — ${email}`,
      html:    `<pre style="font-family:monospace">${slackText(TYPE_LABELS[type] ?? type, email)}</pre>`,
    })
  }
}

function appendToStore(entry: Record<string, string>) {
  if (!STORE_PATH) return
  try {
    const dir = path.dirname(STORE_PATH)
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
    const existing: unknown[] = fs.existsSync(STORE_PATH)
      ? JSON.parse(fs.readFileSync(STORE_PATH, 'utf8'))
      : []
    existing.push(entry)
    fs.writeFileSync(STORE_PATH, JSON.stringify(existing, null, 2))
  } catch (err) {
    console.warn('Waitlist file store failed (non-critical):', err)
  }
}

// ── Route ─────────────────────────────────────────────────────────────────────

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { email, company, type, team_size } = body

    if (!email || !email.includes('@')) {
      return NextResponse.json({ error: 'Valid email required' }, { status: 400 })
    }
    if (!['access', 'demo', 'waitlist'].includes(type)) {
      return NextResponse.json({ error: 'Invalid type' }, { status: 400 })
    }

    const label = TYPE_LABELS[type] ?? 'Signup'
    const entry = {
      email, company: company ?? '', type,
      team_size: team_size ?? '',
      submitted_at: new Date().toISOString(),
    }

    // Run all side-effects in parallel — a failure in one doesn't block the others
    const results = await Promise.allSettled([
      notifySlack(label, email, company, team_size),
      sendConfirmation(type, email),
    ])
    results.forEach(r => { if (r.status === 'rejected') console.error('Waitlist side-effect failed:', r.reason) })

    // File store is synchronous — safe to call after async work
    appendToStore(entry)

    return NextResponse.json({ ok: true, type, email })
  } catch (err) {
    console.error('Waitlist API error:', err)
    return NextResponse.json({ error: 'Internal error' }, { status: 500 })
  }
}
