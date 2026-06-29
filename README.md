# Shelton's Toolkit

A Claude Code plugin with opinionated skills for code review, quality checks, and developer workflows.

## Install

```bash
/plugin marketplace add sheltoncyril/sheltons-toolkit
```

## Skills

| Skill | Invoke | What it does |
|-------|--------|--------------|
| `review` | `/sheltons-toolkit:review <PR-URL>` | Multi-persona PR review with confidence scoring |

## How `review` works

Spawns 3 parallel review agents — each with a different personality and focus area:

| Persona | Focus | Catches |
|---------|-------|---------|
| **Chill** | Correctness & safety only | Bugs, security issues, breaking changes |
| **Grumpy** | Thoroughness | API design, style, AI-generated code smells, ceremony |
| **Unhinged** | Everything + approach | Over-engineering, PR hygiene, commit crimes, plausible-but-wrong code |

Findings are merged with confidence scoring:
- **3/3 agree** → High confidence — definitely real
- **2/3 agree** → Medium confidence — likely real
- **1/3 only** → Low confidence — might be noise

After review, optionally post findings as inline PR comments (asks before posting).

## Usage

```
/sheltons-toolkit:review https://github.com/org/repo/pull/123
```

## Contributing

PRs welcome. Add skills under `skills/<skill-name>/SKILL.md`.

## License

MIT
