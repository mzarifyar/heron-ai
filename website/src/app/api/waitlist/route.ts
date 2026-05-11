import { NextRequest, NextResponse } from 'next/server'

const SLACK_WEBHOOK = process.env.SLACK_WEBHOOK_URL ?? ''

const TYPE_LABELS: Record<string, string> = {
  access:   '🚀 Early Access Request',
  demo:     '📅 Demo Request',
  waitlist: '📋 Waitlist Signup',
}

const TYPE_EMOJI: Record<string, string> = {
  access:   '🚀',
  demo:     '📅',
  waitlist: '📋',
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { email, company, type, team_size } = body

    // Validate
    if (!email || !email.includes('@')) {
      return NextResponse.json({ error: 'Valid email required' }, { status: 400 })
    }
    if (!['access', 'demo', 'waitlist'].includes(type)) {
      return NextResponse.json({ error: 'Invalid type' }, { status: 400 })
    }

    const label = TYPE_LABELS[type] ?? 'Signup'
    const emoji = TYPE_EMOJI[type] ?? '📩'
    const ts    = new Date().toISOString()

    // Post to Slack
    if (SLACK_WEBHOOK) {
      const lines = [
        `*${label}*`,
        `*Email:* ${email}`,
        company  ? `*Company:* ${company}`         : null,
        team_size? `*Team size:* ${team_size}`      : null,
        `*Time:* ${ts}`,
        `*Source:* heron-ai.net`,
      ].filter(Boolean).join('\n')

      await fetch(SLACK_WEBHOOK, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: `${emoji} New ${label.toLowerCase()} from *${email}*`,
          blocks: [
            {
              type: 'section',
              text: { type: 'mrkdwn', text: lines },
            },
            {
              type: 'divider',
            },
          ],
        }),
      })
    }

    return NextResponse.json({
      ok: true,
      message: 'Submission received',
      type,
      email,
    })
  } catch (err) {
    console.error('Waitlist API error:', err)
    return NextResponse.json({ error: 'Internal error' }, { status: 500 })
  }
}
