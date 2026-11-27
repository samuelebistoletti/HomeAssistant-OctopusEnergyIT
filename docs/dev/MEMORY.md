# Working memory

Where the work stands, the next step and the operating facts no other file states. Short, factual, public: no
personal data, credentials, account numbers or machine paths. "Now" is rewritten at every checkpoint (`CLAUDE.md`
"Sessions").

## Now (2026-11-27)

- **1.3.0** released. Unreleased on `main` (not yet versioned): minimum HA 2025.11.0 (needed by the statistics
  `unit_class` field), `claude-code-action` pinned to a commit SHA (CodeQL alerts #15-#17), `.build/` removed, the
  migration off the Kraken fields deprecated in November 2026 (`status.current`, ledger `balance`), and #36: charging
  session history (smart / boost kWh) and the estimated Intelligent Octopus saving as external statistics, with a
  discount number entity. Verified live on the dev HA.
- Kraken deprecated the OCPP onboarding API (`ocppDetails`, `ocppConnection`, `ocppAuthentication`; removal from
  2027-01-23): do not build on it.
- No open issues. Next step: decide the next release (1.4.0, with #36), or pick new work.

## Operating facts

- Commits go straight to `main` after the owner has seen a preview; no feature branches (the owner bypasses the
  "Protect main" ruleset; the Claude GitHub agent works through PRs).
- Dev stack: `docker compose up -d` (HA :8123, ha-mcp :8086); the dev login and ha-mcp token are in `config/.dev/`
  (gitignored).
- Live tests run against the owner's real Octopus account. Never send a real gas self-reading. Tests on the owner's car
  are allowed; afterwards restore its settings (target 100 %, ready by 04:00, smart charging on).
