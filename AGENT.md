Working agreement for humans and coding agents in this repository.

Repo domain: Heron reliability platform (incident-response loop, safety guardrails, explainability, and Chronicle learning surfaces).

------------------------------------------------------------
1) Primary Goal
------------------------------------------------------------

Make safe, correct, testable changes that improve Heron behavior and operator/developer usability while preserving trust, auditability, and policy constraints.

Default priority order:
1. correctness and safety
2. preserve existing behavior unless change is explicit
3. observability and explainability
4. maintainability and clarity
5. speed

------------------------------------------------------------
2) Scope and Boundaries
------------------------------------------------------------

- Treat this repo as production reliability software.
- Prefer small, reversible changes; avoid broad refactors unless requested.
- Keep API/data contracts stable unless the user requests a change.
- Do not add external services/telemetry dependencies unless explicitly requested.
- Never add or expose secrets (code, docs, logs, tests, commits).

------------------------------------------------------------
3) Source Hierarchy (conflict resolution)
------------------------------------------------------------

Use sources in this order:
1. user request in the current thread (most recent + most explicit)
2. this AGENT.md
3. vision_doc.md
4. existing code + tests
5. README.md

If sources conflict, follow the highest-ranked source; when uncertain, ask a clarifying question before changing behavior.

------------------------------------------------------------
4) Change Design Rules
------------------------------------------------------------

- Keep the Observe -> Detect -> Decide -> Act -> Verify -> Escalate -> Learn loop explicit.
- Preserve explainability: decisions/actions must be auditable (logs/metrics/traces as appropriate).
- Preserve policy authority boundaries (no hidden bypasses).
- Fail safely: graceful degradation in non-critical paths; explicit errors in critical paths.
- Keep data contracts explicit and typed; document breaking changes.

------------------------------------------------------------
5) Testing and Validation Expectations
------------------------------------------------------------

For meaningful code changes:
- run targeted tests for touched areas
- run full test suite for cross-cutting changes
- run lint/format checks when applicable
- run a smoke path when runtime/deploy behavior changes

If checks cannot be run, state what was skipped and why (and the risk).

------------------------------------------------------------
6) Documentation Rules
------------------------------------------------------------

- Keep README.md user-operational and current.
- Document intent and operation; do not hide uncertainty.
- Update docs only when behavior or workflow changes.

------------------------------------------------------------
7) Editing Guidance
------------------------------------------------------------

- Prefer focused patches with clear intent; avoid unrelated churn.
- Do not rename/move large structures unless requested.
- Keep naming, style, and patterns consistent with surrounding code.
- Add comments/docstrings only when they improve comprehension.

Pseudocode policy:
- Add pseudocode only when requested or when it materially clarifies a complex change.
- If pseudocode is added, follow PSEUDOCODE_GUIDE.txt exactly.

Docstring policy (plain English):
- When asked to "document what code does," use 1-sentence docstrings that describe behavior + return + failures, without step-by-step control flow.

------------------------------------------------------------
8) Operational Safety
------------------------------------------------------------

- Never commit secrets.
- Do not hardcode machine-specific personal paths unless explicitly required and documented.
- Prefer repo-local, reproducible workflows over one-off machine tweaks.

------------------------------------------------------------
9) Communication Contract
------------------------------------------------------------

- Be explicit about assumptions.
- Report what changed, why, and how it was validated.
- Surface risks and follow-ups plainly.
- When blocked, provide the smallest actionable next step.

------------------------------------------------------------
10) Maintenance of This File
------------------------------------------------------------

Keep this file durable and repo-scoped:
- stable working rules only
- no temporary status, snapshots, or one-off task notes
- update only when team workflow/guardrails materially change
