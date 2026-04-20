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

## How to use it

1. Copy the `zhanggong-impact-blueprint` folder into the repository where you want to use it, under `./.agents/skills/`.
2. After that, the target path should be `./.agents/skills/zhanggong-impact-blueprint/`.
3. In your conversations with AI, explicitly tell it to use this skill.
4. Your job is mostly to describe what you want changed. The AI using this skill should decide when to run `analyze` and when to run `finish` according to the rules.

For normal use, you usually do not need to run the internal commands by hand. Those commands are more for maintenance, troubleshooting, or verifying the skill itself.

