# Working memory

Where the work stands, the next step and the operating facts no other file states. Short, factual, public: no
personal data, credentials, account numbers or machine paths. "Now" is rewritten at every checkpoint (`CLAUDE.md`
"Sessions").

## Now (2026-11-25)

- **1.3.0b1** is out as a pre-release; v1.2.5 stays Latest.
- **#26**: the reporter runs the beta. The 4 statistics repairs they saw are the 2 contract-expiry sensors times
  `units_changed` + `mean_type_changed` (fix: delete the old statistics); CHANGELOG and release notes corrected
  (a65c627). Waiting for their diagnostics if negative deltas recur.
- **Next**: when the beta is confirmed, release 1.3.0 final: `manifest.json` to `1.3.0`, rename the CHANGELOG section
  `[1.3.0b1]` to `[1.3.0]`, preview, push to `main`.
- Open work is tracked in GitHub issues (labels in `docs/agents/triage-labels.md`).

## Operating facts

- Commits go straight to `main` after the owner has seen a preview; no feature branches.
- Dev stack: `docker compose up -d` (HA :8123, ha-mcp :8086); the dev login and ha-mcp token are in `config/.dev/`
  (gitignored).
- Live tests run against the owner's real Octopus account. Never send a real gas self-reading. Tests on the owner's car
  are allowed; afterwards restore its settings (target 100 %, ready by 04:00, smart charging on).
