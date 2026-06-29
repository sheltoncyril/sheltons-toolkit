# Shelton's Toolkit

A Claude Code plugin with opinionated code review skills at three intensity levels — plus whatever else ends up being useful.

## Install

```bash
/plugin marketplace add sheltoncyril/sheltons-toolkit
```

## Skills

| Skill | Invoke | Intensity |
|-------|--------|-----------|
| `chill-review` | `/sheltons-toolkit:chill-review <PR-URL>` | Laid back. Only flags real issues. |
| `grumpy-review` | `/sheltons-toolkit:grumpy-review <PR-URL>` | Blunt, thorough, skeptical. |
| `unhinged-review` | `/sheltons-toolkit:unhinged-review <PR-URL>` | Chaotic. Roasts everything. Still accurate. |

## Usage

```
/sheltons-toolkit:chill-review https://github.com/org/repo/pull/123
/sheltons-toolkit:grumpy-review https://github.com/org/repo/pull/123
/sheltons-toolkit:unhinged-review https://github.com/org/repo/pull/123
```

## Contributing

PRs welcome. Add skills under `skills/<skill-name>/SKILL.md`.

## License

MIT
