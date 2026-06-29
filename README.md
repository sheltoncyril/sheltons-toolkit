# Shelton's Toolkit

A Claude Code plugin with opinionated skills for code review, quality checks, and developer workflows.

## Install

```bash
/plugin marketplace add sheltoncyril/sheltons-toolkit
```

## Skills

| Skill | Invoke | Description |
|-------|--------|-------------|
| `codex-review` | `/sheltons-toolkit:codex-review <PR-URL>` | Grumpy senior reviewer persona for AI-generated PRs |

## Usage

```
/sheltons-toolkit:codex-review https://github.com/org/repo/pull/123
```

## Contributing

PRs welcome. Add skills under `skills/<skill-name>/SKILL.md`.

## License

MIT
