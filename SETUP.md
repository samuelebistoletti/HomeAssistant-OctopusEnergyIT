# Claudify — Quick Start

You're 3 steps from a production-grade Claude Code system.

---

## 1. Install Claude Code

Skip this if you already have Claude Code installed (`claude --version` to check).

```bash
# Mac / Linux / WSL
curl -fsSL https://claude.ai/install.sh | bash

# Windows PowerShell
irm https://claude.ai/install.ps1 | iex
```

Requires a paid Anthropic plan (Pro $20/mo, Max $100-200/mo, or Teams/Enterprise).

> **Heads up:** If you have an `ANTHROPIC_API_KEY` environment variable set, Claude Code bills to your API account instead of your subscription. Run `unset ANTHROPIC_API_KEY` if that's not what you want.

> **Prerequisite:** The safety hooks require `jq` (a command-line JSON processor). Install it if you don't have it:
> ```bash
> # Mac
> brew install jq
>
> # Ubuntu / Debian
> sudo apt-get install jq
>
> # Windows (via Chocolatey)
> choco install jq
> ```
> Verify with `jq --version`. Without `jq`, hooks will still run but safety checks (backup verification, completeness gates, dangerous command blocking) will silently skip.

## 2. Copy files into your project

Unzip and copy everything into your project root:

```bash
cd /path/to/your/project
cp -r /path/to/claudify-download/* .
cp -r /path/to/claudify-download/.claude .
```

This adds the `.claude/` system directory, `CLAUDE.md`, `Task Board.md`, `Scratchpad.md`, and `Daily Notes/`.

If you already have a `.claude/` directory, merge manually — don't overwrite your existing settings or memory.

## 3. Start Claude Code and run the onboarding prompt

```bash
claude
```

Then paste the onboarding prompt below. This tells Claude to scan your project, adopt the Claudify system, and configure everything for your specific setup.

---

## Onboarding Prompt (copy and paste this into Claude Code)

```
I just installed the Claudify operating system into this project. The system files are in .claude/ and the main instructions are in CLAUDE.md.

Please do the following:

1. Read CLAUDE.md to understand the full system architecture.
2. Read .claude/memory.md and .claude/knowledge-base.md.
3. Read .claude/command-index.md to learn all available commands.
4. Scan my project structure (files, folders, language, framework, dependencies).
5. Based on what you find, show me a summary of what you detected.
6. Then ask me a few smart questions to tailor the system to my needs:
   - What are my main goals with this project?
   - What does my typical workflow look like?
   - What tasks do I spend the most time on (or want to automate)?
   - Are there any tools, platforms, or services I use regularly?
7. Based on my answers and your scan, update memory.md with:
   - Project name and description
   - Language/framework/build tool
   - Key file paths
   - Any patterns you noticed
   - My goals and workflow preferences
8. Review the skills in .claude/skills/ — recommend the categories and specific skills most relevant to my project and goals.
9. Run /start to initialise the daily workflow.

Scan first, then ask questions — don't wait for me before doing the initial scan.
```

---

## What you just installed

**6-layer memory** — Claude remembers context across sessions, learns from mistakes, and gets better over time.

**9 specialist agents** — Auditor (quality gate), Unsticker, Error Whisperer, Rubber Duck, PR Ghostwriter, Yak-Shave Detector, Debt Collector, Onboarding Sherpa, Archaeologist. They run automatically via commands.

**21 commands** — `/start`, `/sync`, `/wrap-up`, `/clear`, `/audit`, `/onboard`, `/review`, `/retro`, `/launch`, `/report`, and more. Type them in Claude Code and the system handles the rest.

**1,727 skills across 31 categories** — Agriculture, AI Automation, Construction, Consulting, Content, Customer Success, Data, Design, Development, Ecommerce, Education, Email, Energy, Finance, Fitness & Wellness, Food & Beverage, Healthcare, HR, Legal, Marketing, Media, Nonprofit, Operations, Product, Productivity, Real Estate, Sales, SEO, Social Media, Startup, Travel.

**9 automated checks** — Deterministic safety nets that run every time: blocks dangerous shell commands, backs up files before overwriting, catches incomplete content, logs everything.

**Self-improvement engine** — Claude observes patterns, nominates learnings, and the auditor promotes confirmed rules. Your system gets smarter the more you use it.

## Daily workflow

```
Morning:    /start → work → /sync (if switching tasks)
Afternoon:  work → /clear (if context gets heavy) → work
Evening:    /wrap-up
```

## Commands

| Command | When to use |
|---|---|
| `/start` | Beginning of a work session |
| `/sync` | Mid-session to refresh context |
| `/clear` | Between unrelated tasks or when quality drops |
| `/wrap-up` | End of a work session |
| `/audit` | After finishing something important |
| `/onboard` | Scan a new codebase for orientation |
| `/unstick` | When you're stuck on a problem |
| `/review` | Get a code or work review |
| `/retro` | Sprint retrospective |
| `/system-audit` | Deep infrastructure health check |
| `/clear` | Resume after losing context or between unrelated tasks |

## FAQ

**Do I need to know how to code?**
No. Everything is plain English.

**Does this work with any project?**
Yes — any language, framework, or structure. The onboarding prompt adapts automatically.

**How do I update?**
Re-download from your purchase link, or run `npx create-claudify update` if you prefer the CLI.

## Tips

1. **Run `/clear` between unrelated tasks.** Context pollution is the #1 quality killer.
2. **Keep memory.md under 100 lines.** Prune aggressively.
3. **Let the knowledge base grow naturally.** Don't pre-fill it — let the auditor promote real learnings.
4. **Trust the hooks.** They catch what instructions miss.
5. **Try `/unstick` when you're blocked.** It's better than spinning.

---

**Need help?** hello@claudify.tech
