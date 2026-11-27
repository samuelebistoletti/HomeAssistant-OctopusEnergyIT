# Working memory

Where the work stands, the next step and the operating facts no other file states. Short, factual, public: no
personal data, credentials, account numbers or machine paths. "Now" is rewritten at every checkpoint (`CLAUDE.md`
"Sessions").

## Now (2026-11-27)

- **1.4.0b1** (beta) prepared on `main` (manifest bumped, CHANGELOG section written); pushing it publishes a GitHub
  pre-release that HACS offers only with betas enabled. It holds:
  #36 (charging session history and estimated Intelligent Octopus saving as external statistics, discount number
  entity, verified live on the dev HA), minimum HA 2025.11.0 (statistics `unit_class`), the migration off the Kraken
  fields deprecated in November 2026 (`status.current`, ledger `balance`; `status_connection_state` attribute removed).
  Also on `main`: `claude-code-action` pinned to a commit SHA (CodeQL #15-#17), `.build/` removed.
- Kraken deprecated the OCPP onboarding API (`ocppDetails`, `ocppConnection`, `ocppAuthentication`; removal from
  2027-01-23): do not build on it.
- No open issues after #36. Next step: watch the 1.4.0b1 release run, collect beta feedback (a user who asked about
  the savings shown in the app was pointed to it), then release 1.4.0.

## Operating facts

- Commits go straight to `main` after the owner has seen a preview; no feature branches (the owner bypasses the
  "Protect main" ruleset; the Claude GitHub agent works through PRs).
- Dev stack: `docker compose up -d` (HA :8123, ha-mcp :8086); the dev login and ha-mcp token are in `config/.dev/`
  (gitignored).
- Live tests run against the owner's real Octopus account. Never send a real gas self-reading. Tests on the owner's car
  are allowed; afterwards restore its settings (target 100 %, ready by 04:00, smart charging on).
