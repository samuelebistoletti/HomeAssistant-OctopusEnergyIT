# Working memory

Where the work stands, the next step and the operating facts no other file states. Short, factual, public: no
personal data, credentials, account numbers or machine paths. "Now" is rewritten at every checkpoint (`CLAUDE.md`
"Sessions").

## Now (2026-11-26)

- **1.3.0b1** is out as a pre-release; v1.2.5 stays Latest. `main` has the fixes for the beta's production outages
  (CHANGELOG `[Unreleased]`): 403s until restart (the shared HA session kept the AWS ALB stickiness cookies; the API
  client now has its own cookie-less session), public tariffs lost on a product republish (versioned product code),
  login storm on HTTP 4xx (5-minute cooldown), stale account sensors staying available.
- #26 and #28 closed (beta working for the reporter; `deltaKwh` no longer requested).
- **Next** (#30): release 1.3.0 final once the fixes have run in production: `manifest.json` to `1.3.0`, merge
  `[Unreleased]` and `[1.3.0b1]` into `[1.3.0]`, preview, push to `main`.
- Open work is tracked in GitHub issues (labels in `docs/agents/triage-labels.md`): #30 release 1.3.0,
  #31 GitHub agent for issues, #32 GitHub MCP plugin auth.

## Operating facts

- Commits go straight to `main` after the owner has seen a preview; no feature branches.
- Dev stack: `docker compose up -d` (HA :8123, ha-mcp :8086); the dev login and ha-mcp token are in `config/.dev/`
  (gitignored).
- Live tests run against the owner's real Octopus account. Never send a real gas self-reading. Tests on the owner's car
  are allowed; afterwards restore its settings (target 100 %, ready by 04:00, smart charging on).
