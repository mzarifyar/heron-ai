# Waitlist Setup

## Active now
Set `SLACK_WEBHOOK_URL` in Vercel env → every submission posts a structured card (email, company, team size).

## To do later — confirmation email
1. Get a free Resend key at resend.com (3,000 emails/month free)
2. Add to Vercel env vars:
   - `RESEND_API_KEY=re_...`
   - `WAITLIST_FROM_EMAIL=Heron <hello@heron-ai.net>`
   - `WAITLIST_NOTIFY_EMAIL=you@yourcompany.com` (optional BCC on every lead)
3. Redeploy
