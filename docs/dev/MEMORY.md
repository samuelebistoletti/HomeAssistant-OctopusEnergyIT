# Working memory

Where the work stands, the next step and the operating facts no other file states. Short, factual, public: no
personal data, credentials, account numbers or machine paths. "Now" is rewritten at every checkpoint (`CLAUDE.md`
"Sessions").

## Now (2026-11-26)

- **1.3.0** released (final; it includes the fixes for the beta's production outages: 403s until restart from the
  shared session's ALB stickiness cookies, public tariffs lost on a product republish, login storm on HTTP 4xx,
  stale account sensors). #26, #28, #30 closed.
- #31: `.github/workflows/claude.yaml` runs the Claude Code action on issues labelled `ready-for-agent` or on
  owner `@claude` mentions, PR-only. Still needed: the `CLAUDE_CODE_OAUTH_TOKEN` secret and the Claude GitHub App
  (`/install-github-app`). The "Protect main" ruleset requires a PR, with a bypass for repo admins.
- #32: the GitHub MCP plugin reads `GITHUB_PERSONAL_ACCESS_TOKEN`; the owner's shell exports it from `gh auth token`.
  Close once the plugin connects after a Claude Code restart.

## Operating facts

- Commits go straight to `main` after the owner has seen a preview; no feature branches (the owner bypasses the
  "Protect main" ruleset; the Claude GitHub agent works through PRs).
- Dev stack: `docker compose up -d` (HA :8123, ha-mcp :8086); the dev login and ha-mcp token are in `config/.dev/`
  (gitignored).
- Live tests run against the owner's real Octopus account. Never send a real gas self-reading. Tests on the owner's car
  are allowed; afterwards restore its settings (target 100 %, ready by 04:00, smart charging on).
