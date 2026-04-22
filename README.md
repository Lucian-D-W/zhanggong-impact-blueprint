# ZhangGong Impact Blueprint skill.md

[English](README.md) | [简体中文](README.zh-CN.md)

## Background Message

> ZhangGong is a friend of mine. He started out drawing construction blueprints on job sites, then one day slapped his thigh and switched into software. After a while he noticed that AI agents edit code like a demolition crew: one hit here, one patch there, no sense of the full structure. ZhangGong slammed the keyboard and said, "Fine. I'll be the chief engineer." So he wrapped himself into a skill that hands agents a proper construction blueprint before they touch anything. These days, every agent in the company is supposed to ask ZhangGong for the drawings before getting to work.

ZhangGong Impact Blueprint is a repo-local impact atlas plus verification guardrail for agent-driven edits.
For the full rules and behavior details, read [`.agents/skills/zhanggong-impact-blueprint/SKILL.md`](E:/AA-HomeforAI/CodeAccounting/.agents/skills/zhanggong-impact-blueprint/SKILL.md:1).

## What It Is

- a copyable skill folder
- a repo-local SQLite graph that persists direct edges only
- a lightweight workflow that shows the impact surface before edits and keeps structured evidence after edits

## What It Is For

- its main job is to put guardrails around AI edits so the model does not start by blindly changing things, especially when context is thin
- it costs more tokens and a few more steps in the short term, but that overhead compounds into a repo that is easier to maintain and easier to hand off
- it is especially useful for context-poor AI, because it lowers the chance of missed chains, repeated debugging, and patch-loop behavior

## When It Fits

- when AI has already become part of your daily development flow instead of being just an occasional helper
- when your project is no longer a throwaway script and needs to survive long-term iteration
- when AI often breaks things because it forgets context, deletes the wrong code, or keeps fixing bugs into worse bugs
- when you want a different model or a later session to pick up the work without starting from zero every time
- when you want "read the impact surface first, then edit, then leave verification evidence" to become a habit

## How To Use It

1. Copy the `zhanggong-impact-blueprint` folder into the target repository under `./.agents/skills/`.
2. The final path should be `./.agents/skills/zhanggong-impact-blueprint/`.
3. When you work with an AI agent, explicitly tell it to use this skill.
4. Your main job is to describe what you want to change. The agent using this skill should decide when to run `analyze` and when to run `finish` according to the skill rules.

For normal usage, you usually do not need to run the CLI commands by hand. The commands are more useful when you are maintaining, debugging, or validating the skill itself.

## Update Note

### Stage 18.1 / v0.18.1-rc1

Current status: `accepted candidate`

Key fixes in this update:

- fix the Windows `.sh` test-entry preflight miss
- fix the GBK / Windows terminal case where tests passed but CLI output failed on encoding
- support Python repositories that use `test/`
- fix flaky baseline / no_regression comparison
- fix stale handoff errors after a successful `finish`
- fix seed-selection mode incorrectly recommending `finish`
- fix contradictory trust explanations
- fix ignored list-form `test_command` values in repo config
