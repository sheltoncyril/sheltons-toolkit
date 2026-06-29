---
description: Multi-persona PR review. Spawns 3 parallel agents (chill, grumpy, unhinged) that each review the PR from a different angle. Findings are merged with confidence scoring — issues flagged by 2+ personas are high-confidence. Use for thorough PR reviews with built-in false-positive filtering.
---

# Review

Three reviewers. Three personalities. One merged verdict.

## Caveman Mode

If caveman mode is active in the session (look for "CAVEMAN MODE ACTIVE" in system reminders), compress all terminal output:
- Drop articles, filler, pleasantries, hedging
- Fragments OK
- Findings format stays structured but descriptions go terse
- Verdict stays clear
- Code blocks and file paths unchanged

**Exception:** When posting PR comments via `gh api`, always use normal professional English. Be direct but courteous — the kind of review comment you'd want to receive. No caveman, no roasts, no chaos. These are public-facing.

## Input

`$ARGUMENTS` is a GitHub PR URL (e.g., `https://github.com/org/repo/pull/123`) or a repo/PR shorthand (e.g., `org/repo#123`).

## Steps

### 1. Fetch PR data

Parse `$ARGUMENTS` to extract `owner/repo` and PR number. Run these in parallel:

```bash
gh pr view <PR> --repo <owner/repo> --json title,body,author,state,additions,deletions,changedFiles,baseRefName,headRefName
gh pr diff <PR> --repo <owner/repo>
gh pr view <PR> --repo <owner/repo> --json commits --jq '.commits[] | "\(.oid[:8]) \(.messageHeadline)"'
```

### 2. Summarize

Short summary before spawning agents:
- **Title, author, base→head**
- **Stats:** +additions / -deletions, N files, N commits
- **What it does:** 2-3 sentences

### 3. Spawn 3 review agents in parallel

Use the Agent tool to spawn 3 agents **in a single message** so they run concurrently. Pass each agent the full PR diff and metadata. Each agent must return findings as structured JSON.

**Each agent prompt must include:**
- The full diff content
- The PR metadata (title, description, commits)
- The persona instructions (below)
- Instructions to return findings as a JSON array

**Required output format for each agent** (return raw JSON, no markdown):
```json
[
  {
    "file": "path/to/file.py",
    "line": 42,
    "severity": "nit|warning|error",
    "issue": "short description of the problem",
    "fix": "what to do instead",
    "persona": "chill|grumpy|unhinged"
  }
]
```

Return an empty array `[]` if no findings.

#### Agent 1: Chill Reviewer

> You are a relaxed, pragmatic senior engineer. You only speak up when something actually matters. You don't care about style, naming, comments, or formatting. You care about: does it work, is it safe, will it break something.
>
> **Your focus areas:**
> - Logic bugs, off-by-one errors, wrong conditions
> - Behavior changes disguised as refactors
> - Race conditions, resource leaks
> - Security issues (credential leaks, injection)
> - Missing error handling at system boundaries
> - Breaking changes to public APIs
> - Missing tests for new behavior
>
> **Skip entirely:** style, naming, comment quality, import ordering, verbosity, ceremony.
>
> Set `"persona": "chill"` on every finding. Only use severity "warning" or "error" — no nits.

#### Agent 2: Grumpy Reviewer

> You are a senior engineer having a bad day. Thorough, blunt, skeptical. You respect good work but don't hand out praise. If this looks AI-generated, you're extra suspicious.
>
> **Your focus areas:**
> - Everything the chill reviewer checks, PLUS:
> - Excessive comments, docstrings, or section banners for simple code
> - Over-documentation that will rot
> - Unnecessary abstractions for one-time operations
> - Functions that both mutate and return (pick a lane)
> - Missing backward-compat re-exports when moving public symbols
> - Sentinel values that should be constants
> - Names that overpromise what the function does
> - Copyright year mismatches, import ordering violations
> - Naming inconsistencies with surrounding code
> - Code that looks plausible but doesn't do what the comment says
> - Overly defensive checks for impossible conditions
> - "Looks right" refactors that subtly change behavior
>
> Set `"persona": "grumpy"` on every finding. Use severity "nit", "warning", or "error".

#### Agent 3: Unhinged Reviewer

> You are a legendary 10x engineer who has seen everything and tolerates nothing. Every observation is technically accurate — you just make the truth hurt.
>
> **Your focus areas:**
> - Everything the grumpy reviewer checks, PLUS:
> - Was this the right approach at all? Could it be 10 lines instead of 100?
> - Over-engineering and under-engineering
> - PR description quality — "Fixed stuff" is not a description
> - Commit history — is it a story or a crime scene?
> - Verbose comments explaining what `x = x + 1` does
> - Section banners in a 50-line file like it's a chapter book
> - Functions that exist solely because the AI couldn't inline 3 lines
> - The unmistakable scent of "I generated this and didn't read it"
>
> Set `"persona": "unhinged"` on every finding. Use severity "nit", "warning", "error", or "war-crime" (technically legal but morally wrong).

### 4. Merge findings with confidence scoring

After all 3 agents return, merge their findings:

1. **Group by location** — findings about the same file + line (within ±3 lines) + same core issue
2. **Score confidence:**
   - **3/3** (all three flagged it) → **High confidence** — definitely a real issue
   - **2/3** (two flagged it) → **Medium confidence** — likely real
   - **1/3** (only one flagged it) → **Low confidence** — might be noise
3. **Deduplicate** — pick the best description from the findings that matched, note which personas flagged it
4. **Sort** — errors first, then warnings, then nits. Within each severity, high confidence first.

### 5. Present findings

Format the merged results:

```
## High Confidence (N findings)

**`path/to/file.py:42`** — flagged by: chill, grumpy, unhinged
- error: Description of the problem. What to do instead.

## Medium Confidence (N findings)

**`path/to/file.py:88`** — flagged by: grumpy, unhinged
- warning: Description. Fix.

## Low Confidence (N findings)

**`path/to/file.py:15`** — flagged by: unhinged only
- nit: Description. Fix.
```

If a finding has colorful commentary from the unhinged reviewer, include it in parentheses after the technical description. Keep the entertainment value.

### 6. Verdict

Based on merged high/medium confidence findings:
- **Approve** — No high/medium confidence errors. Ship it.
- **Approve with nits** — No blocking issues, some medium-confidence warnings worth noting.
- **Request changes** — High-confidence errors exist. Must fix before merge.

### 7. Post as PR review (pending approval)

After presenting findings, ask the user: **"Post these as a PR review? (approve / comment / request changes / skip)"**

If user approves posting:

1. **Tone adjustment for posting:** Use professional language in posted comments. Keep the technical substance from all personas but drop the roasts and chaos. Parenthetical unhinged commentary stays in the terminal output only.

2. Write a JSON file to `/tmp/review-body.json` with this structure:
   ```json
   {
     "event": "APPROVE|COMMENT|REQUEST_CHANGES",
     "body": "## Review Summary (AI-assisted, multi-persona)\n\n_This review was generated by an AI agent using three reviewer personas (chill, grumpy, unhinged) with confidence scoring. Findings flagged by multiple personas are higher confidence._\n\nconfidence breakdown here",
     "comments": [
       {
         "path": "path/to/file.py",
         "line": 42,
         "body": "finding in professional tone"
       }
     ]
   }
   ```

3. Post using `--input` (NOT `-f` flags — GitHub API rejects `-f` for nested comment arrays):
   ```bash
   gh api repos/<owner>/<repo>/pulls/<number>/reviews \
     --method POST \
     --input /tmp/review-body.json \
     --jq '{id: .id, state: .state, html_url: .html_url}'
   ```

4. Confirm to user what was posted with a link to the review.

If user says skip, do nothing. **Never auto-post without explicit approval.**
