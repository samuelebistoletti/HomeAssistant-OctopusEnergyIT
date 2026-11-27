# Working memory

Where the work stands, the next step and the operating facts no other file states. Short, factual, public: no
personal data, credentials, account numbers or machine paths. "Now" is rewritten at every checkpoint (`CLAUDE.md`
"Sessions").

## Now (2026-11-27)

- **1.4.0b1** (beta) released as a GitHub pre-release; all workflows green, no open code-scanning alerts. It holds:
  #36 (charging session history and estimated Intelligent Octopus saving as external statistics, discount number
  entity, verified live on the dev HA), minimum HA 2025.11.0 (statistics `unit_class`), the migration off the Kraken
  fields deprecated in November 2026 (`status.current`, ledger `balance`; `status_connection_state` attribute removed).
- Kraken deprecated the OCPP onboarding API (`ocppDetails`, `ocppConnection`, `ocppAuthentication`; removal from
  2027-01-23): do not build on it.
- The user who asked about the savings shown in the app was pointed to the beta and asked to compare the numbers.
- No open issues. Next step: collect beta feedback, then release 1.4.0 (rename the CHANGELOG section, bump the
  manifest).

## Operating facts

- Commits go straight to `main` after the owner has seen a preview; no feature branches (the owner bypasses the
  "Protect main" ruleset; the Claude GitHub agent works through PRs).
- Dev stack: `docker compose up -d` (HA :8123, ha-mcp :8086); the dev login and ha-mcp token are in `config/.dev/`
  (gitignored).
- Live tests run against the owner's real Octopus account. Never send a real gas self-reading. Tests on the owner's car
  are allowed; afterwards restore its settings (target 100 %, ready by 04:00, smart charging on).
