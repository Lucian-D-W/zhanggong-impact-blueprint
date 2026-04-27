# ZhangGong Blueprint.skill

[English](README.md) | [简体中文](README.zh-CN.md)

## Background Message

> ZhangGong is a friend of mine. In his early years he was a civil-engineering guy drawing construction blueprints on job sites, then one day he slapped his thigh and switched into software. After a while he discovered that AI agents edit code like a demolition crew: one hit here, one patch there, with no sense of the whole structure. ZhangGong slapped the keyboard and said, "Fine. I'll be your chief engineer." From then on he packaged himself into a skill whose job is to hand detailed construction drawings to every kind of agent. These days, every agent in the company is supposed to ask ZhangGong for the drawings before starting work.

ZhangGong Impact Blueprint is a repo-local impact graph and verification workflow harness for agent-driven changes.
For the full rules and detailed behavior, read [`.agents/skills/zhanggong-impact-blueprint/SKILL.md`](E:/AA-HomeforAI/CodeAccounting/.agents/skills/zhanggong-impact-blueprint/SKILL.md:1).
If you prefer reviewing in Chinese, start with the Chinese README; the skill body currently follows `SKILL.md`.

## What It Is

- a copyable skill folder
- a low-friction workflow that shows the impact reading surface before behavior-changing edits and keeps structured evidence after edits
- a restrained working agreement so ordinary docs are not forced into the full workflow

## What It Is For

- its core job is to put rules around AI work: do not start by changing things blindly. Especially when context is thin, it helps reduce missed chains, repeated debugging, and the habit of piling patch after patch into a dead loop. It teaches the agent that ignoring today's hidden risk is how tomorrow's accident comes to collect.
- it costs more tokens and a few more steps in the short term, but it compounds over time: the project becomes easier to maintain and easier to hand off, and you do not need to reteach everything from zero every time you switch to a different AI
- it is especially friendly to context-poor AI, because it can pull the model out of the trap of "local wall-patching + endless bug-fix looping" and force it to read the impact surface before editing

## How To Use It

1. Copy the `zhanggong-impact-blueprint` folder into the repository where you want to use it, under `./.agents/skills/`.
2. The target path should then be `./.agents/skills/zhanggong-impact-blueprint/`.
3. After that, when you interact with an AI, explicitly tell it to use this skill.
4. What you really need to do is describe what you want to change; when to run `analyze` and when to run `finish` should be decided by the AI using this skill according to the rules.

For normal usage, you usually do not need to run these CLI commands by hand. The CLI is more for maintaining, troubleshooting, or validating the skill itself.

## When It Fits

- when AI has already become part of your daily workflow rather than an occasional little tool for looking up an error
- when your project is no longer a throwaway script, but old code that has to live for a long time and be changed again and again
- when you notice AI often breaks things because it cannot hold context, deletes the wrong code, changes logic blindly, or turns one bug fix into three more
- when you want a different AI or a later conversation to take over without staring blankly and needing the whole project explained from zero again
- when you want "read the impact surface before changing code, and leave a verification record after editing" to become part of the team's DNA

## Update Notes

### Stage 21 / v0.21.0

Key changes:

- split workflow into bypass / lightweight / full guardian, so lightweight tasks are no longer forced through the full flow
- make `analyze` a short brief by default, with facts, inferences, and summary saved separately
- clarify GitNexus-first, with explicit reasons for fallback
- stop hard-interrupting multi-entry tasks by default
- make trust explanatory, and make setup more restrained by default
- make `finish` verify the current task by default, and separate tests passed, targeted coverage, and baseline red

### Stage 20 / v0.20.0-rc1

Key changes:

- add a provider abstraction layer
- integrate stronger gitnexus analysis
- default `graph_provider = gitnexus`
- automatically fall back to the internal provider when `GitNexus` fails

### Stage 18.1 / v0.18.1-rc1

The main fixes include:

- fix the missed preflight detection for `.sh` test entrypoints on Windows
- fix the GBK / Windows terminal case where tests had already passed but the CLI still failed on output encoding
- support Python repositories that use a `test/` directory
- fix flaky baseline / no_regression judgment
- fix stale handoff errors remaining after a successful `finish`
- fix `next-action` incorrectly recommending `finish` before a seed was selected
- fix contradictory trust explanations
- fix ignored list-form `test_command` values in repo config

## Acknowledgements

In the Stage 21 shape, this project prioritizes GitNexus as the primary graph fact source.
Thanks to [GitNexus](https://github.com/abhigyanpatwari/GitNexus) for the stronger local graph, upstream/downstream impact, and process-chain visibility.
