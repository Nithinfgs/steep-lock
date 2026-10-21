# Research and decision record

Observed 2026-10-21 (all figures are point-in-time reads, not verified beyond the API/page).

## Sources and signals

| Source | What it showed |
|---|---|
| [GitHub trending, weekly](https://github.com/trending?since=weekly) | Agent tooling dominates: morluto/rea (355,903 stars, +157,631/wk), stablyai/orca (100,920), ruvnet/ruflo (78,148), opencode (219,570), mksglu/context-mode (31,607), HKUDS/CLI-Anything (55,861), heygen-com/hyperframes (69,048), K-Dense-AI/scientific-agent-skills (53,538), anthropics/claude-plugins-official (43,575), debpalash/VoiceStudio (80,037), akitaonrails/ai-memory (12,175), earthtojake/text-to-cad (22,216), cursor/plugins (13,362), wshobson/agents (41,437), android/skills (9,130), NSA/ghidra (92,528) |
| GitHub Search API, repos created in last 30 days by stars | Several new repos have tens of thousands of stars within weeks (e.g. storytold/photocraft, 70,447). I did not investigate whether these counts are organic; treat the rankings as hype-prone |
| GitHub Search API, "security scanner for agent skills" | NVIDIA/SkillSpector (20,795), Tencent/AI-Infra-Guard (6,929), snyk/agent-scan (3,161), cisco-ai-defense/skill-scanner (2,619): crowded |
| GitHub Search API, "AGENTS.md / CLAUDE.md linter" | agent-sh/agnix (456), alint, agentlinter, driftlint, ctxlint, claudelint, cclint: crowded |
| GitHub Search API, "skills lockfile" | ~6 repos with 0-1 stars (skill-lock x2, skillpack, skillock, mdr, capsule): crowded and tiny |
| GitHub Search API, "dependency cooldown lockfile" | [OrtaMarco/dep-cooldown](https://github.com/OrtaMarco/dep-cooldown) (1 star, JS, npm-only), Veliora-pte-ltd/npm-cooldown (0 stars): thin, single-ecosystem |
| [Hacker News front page](https://news.ycombinator.com/), via Firebase API | [Compromised LiteLLM 1.107.0 on PyPI](https://safedep.io/litellm-pypi-compromise-credential-stealer-backdoor/) (179 pts), PHP2Shell RCE found by AI (392), PHP security release (754), DuckDB 2.0 (234) |
| [Thoughtworks Radar: agent instruction bloat](https://www.thoughtworks.com/radar/techniques/agent-instruction-bloat) | Developers complain about bloated/drifting AGENTS.md / CLAUDE.md |
| [Snyk ToxicSkills](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub) | Supply-chain risk in agent skills (Snyk reports 13% of 3,984 scanned skills with a critical issue) |

Not covered: Reddit and Product Hunt could not be queried directly with the tools available here.

## Opportunities scored

Weights: demand 25, differentiation 20, feasibility 20, usefulness 20, testability/maintainability 15.
Scores are 1-5, total is out of 100.

| # | Opportunity | Demand | Diff. | Feas. | Useful | Test | Total |
|---|---|---|---|---|---|---|---|
| A | Cross-ecosystem cooldown + provenance-regression lockfile auditor | 4 | 4 | 5 | 5 | 5 | **91** |
| B | Agent instruction-file linter | 4 | 1 | 5 | 3 | 5 | 71 |
| C | Agent-skill security scanner | 5 | 1 | 3 | 4 | 3 | 66 |
| D | Lockfile for agent skills | 4 | 2 | 5 | 3 | 5 | 75 |
| E | Local agent-transcript token profiler | 4 | 2 | 4 | 4 | 3 | 69 |

The scores are my judgement from the evidence above, not a measured result.

## Decision: A, `steep-lock`

- **Problem:** fresh malicious releases (LiteLLM, today) get installed during the hours before removal.
- **Users:** maintainers and CI owners with npm, PyPI, Rust or Go lockfiles.
- **Why now:** the LiteLLM compromise is on today's HN front page; the affected releases lacked provenance.
- **Different:** multi-ecosystem, reads existing lockfiles, adds a provenance-regression signal and PR-diff mode; existing cooldown tools found are npm-only or are package-manager settings.
- **Acceptance criteria:** parses 7 lockfile formats; four rules fire correctly against realistic registry responses; `--base` checks only new versions; runs against live registries; zero runtime deps; tests, lint, mypy and pip-audit pass.
