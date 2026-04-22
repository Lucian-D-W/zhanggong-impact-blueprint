# ZhangGong Impact Blueprint skill.md

[English](README.md) | [简体中文](README.zh-CN.md)

## Background Message

> ZhangGong is a friend of mine. He started out drawing construction blueprints on job sites, then one day slapped his thigh and switched into software. After a while he noticed that AI agents edit code like a demolition crew: one hit here, one patch there, no sense of the full structure. ZhangGong slammed the keyboard and said, "Fine. I'll be the chief engineer." So he wrapped himself into a skill that hands agents a proper construction blueprint before they touch anything. These days, every agent in the company is supposed to ask ZhangGong for the drawings before getting to work.

Formal name: `张工的施工图 / ZhangGong Impact Blueprint`

ZhangGong Impact Blueprint is a repo-local impact atlas plus verification guardrail for agent-driven edits.
For the full rules and behavior details, read [`.agents/skills/zhanggong-impact-blueprint/SKILL.md`](E:/AA-HomeforAI/CodeAccounting/.agents/skills/zhanggong-impact-blueprint/SKILL.md:1).

## What it is

- a copyable skill folder
- a repo-local SQLite graph that persists direct edges only
- a lightweight workflow that shows the impact surface before edits and keeps structured evidence after edits

## What it is for

- its main job is to put guardrails around AI edits so the model does not start by blindly changing things
- it makes the project easier to maintain and easier to hand off over the long run
- it costs more tokens and a few more steps in the short term, but it can compound over time
- it is especially useful for context-poor AI, because it lowers the chance of bad edits, missed chains, repeated debugging, and patch-loop behavior

## When it fits

- when AI has already become part of your daily development flow instead of being just an occasional helper
- when your project is no longer a throwaway script and needs to survive long-term iteration
- when AI often breaks things because it forgets context, deletes the wrong code, or keeps fixing bugs into worse bugs
- when you want a different model or a later session to pick up the work without starting from zero every time
- when you want "read the impact surface first, then edit, then leave verification evidence" to become a habit

## Real repo flow

The final skill name is `zhanggong-impact-blueprint`.

For a real repository, the recommended flow is:

1. `python .agents/skills/zhanggong-impact-blueprint/cig.py setup --minimal --project-root . --dry-run`
2. `python .agents/skills/zhanggong-impact-blueprint/cig.py setup --minimal --project-root .`
3. `python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .`
4. `python .agents/skills/zhanggong-impact-blueprint/cig.py health --workspace-root .`
5. `python .agents/skills/zhanggong-impact-blueprint/cig.py build --workspace-root .`
6. `python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file <path>`
7. `python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted`

`setup` now defaults to `minimal`. Use `--full` only when you explicitly want the consumer docs, AGENTS managed block, and runtime docs. Use `--dry-run` first if you want to preview what setup would create or update.

Release prep status: `Stage 18.1 accepted candidate` / `v0.18.1-rc1`

This release candidate is accepted for the Stage 18 user-feedback blocker scope. It is not described as fully proven across all historical stages.

## Calibration rules

Stage 18 is about repo reality calibration, not adding heavier machinery.

- repo-local config wins over profile fallback
- recent successful test command wins over default guessing
- package scripts beat profile fallback
- profile fallback beats adapter default
- `primary_adapter` decides the main graph and finish verification
- `supplemental_adapters` can add indexing coverage, but they do not take over the repo
- `calibrate` is the step that checks whether the current repo reality matches your config and chosen profile
- `baseline` is the step that lets `finish` distinguish historical red from a new regression

The test command order is now:

`repo config > recent successful command > package script > profile fallback > adapter default`

## Examples

Mixed-language repo:

```json
{
  "primary_adapter": "tsjs",
  "supplemental_adapters": ["python"]
}
```

Historically red repo:

1. capture baseline with `python .agents/skills/zhanggong-impact-blueprint/cig.py baseline --workspace-root . --capture-current`
2. run a smoke or targeted finish
3. read `regression_status` instead of pretending every failure is new

Windows shell risk:

- direct `.sh` test commands can fail on Windows
- CRLF shell scripts can fail even when bash exists
- prefer cross-platform `npm`, `pnpm`, `bun`, or `node` scripts for repo-facing verification

Analyze output:

- default terminal output is brief
- long JSON still lands in `.ai/codegraph/reports/`
- use `--json` or `--full-json` when a script needs the full payload

