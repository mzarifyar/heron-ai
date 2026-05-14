# Local Development Setup Notes

These are the tweaks required to run Heron locally without access to AWS secret
service, Monitoring (T2), or the hosted GenAI agent:

- Copy `.env.example` to `.env` and populate the following keys:
  - `JIRA_BEARER_TOKEN` – Jira API token.
  - `MCP_API_KEY` – Knowledge-layer MCP key.
  - `MCP_BASE_URL` – Optional override if pointing at a non-default MCP endpoint.
  - `HERON_DISABLE_AI=1` – Skips GenAI agent calls when running offline.
  - `TELEMETRY_ENABLED=false` – Prevents attempts to push metrics to AWS Monitoring.
- The application auto-loads `.env` via `python-dotenv`; no code changes are
  needed in other modules.
- Secret service initialization now checks whether the required env vars are set
  and logs a warning instead of failing when they are absent.
- AI evaluation short-circuits when `HERON_DISABLE_AI` is set, returning a
  descriptive error for downstream logging.

When switching branches, re-apply the above configuration (or cherry-pick the
commits touching:
`application/ai_evaluator.py`, `.env.example`, `README.md`, and this file).
