# Working memory

Where the work stands, the next step and the operating facts no other file states. Short, factual, public: no
personal data, credentials, account numbers or machine paths. "Now" is rewritten at every checkpoint (`CLAUDE.md`
"Sessions").

## Now (2026-11-26)

- **1.3.0** released (final; it includes the fixes for the beta's production outages: 403s until restart from the
  shared session's ALB stickiness cookies, public tariffs lost on a product republish, login storm on HTTP 4xx,
  stale account sensors). #26, #28, #30 closed.
- #31 closed: the Claude GitHub agent (`.github/workflows/claude.yaml`) is active. It runs on issues labelled
  `ready-for-agent` and on owner `@claude` mentions and works only through PRs; Claude Code Review also reviews its
  PRs. First end-to-end run: #34 → #35 (TECHNICAL_NOTES now describes the per-entry API session), merged.
- #32 closed: the GitHub MCP plugin connects (it reads `GITHUB_PERSONAL_ACCESS_TOKEN`, exported from `gh auth token`).
- No open issues. Next step: pick new work from user reports or the roadmap.

## Operating facts

- Commits go straight to `main` after the owner has seen a preview; no feature branches (the owner bypasses the
  "Protect main" ruleset; the Claude GitHub agent works through PRs).
- Dev stack: `docker compose up -d` (HA :8123, ha-mcp :8086); the dev login and ha-mcp token are in `config/.dev/`
  (gitignored).
- Live tests run against the owner's real Octopus account. Never send a real gas self-reading. Tests on the owner's car
  are allowed; afterwards restore its settings (target 100 %, ready by 04:00, smart charging on).
