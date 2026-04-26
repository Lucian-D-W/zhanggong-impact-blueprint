# Real Repository Rollout Checklist

Use this checklist when adopting ZG Impact Blueprint in an existing repo.

## 1. Minimal Entry

Start with preview, then minimal setup:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root . --dry-run --preview-changes
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root .
```

Minimal setup writes only runtime essentials:

- `.zhanggong-impact-blueprint/config.json`
- `.zhanggong-impact-blueprint/schema.sql`
- `.ai/codegraph/`
- managed `.gitignore` block

Use `--full` only when you want onboarding docs, consumer guide, and AGENTS integration.

## 2. Calibrate Reality

Run:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py health --workspace-root .
```

Confirm:

- provider status and fallback reason
- adapter choice
- selected test command
- why ignored test commands lost
- baseline status if already captured

Selection priority is:

1. repo config
2. recent successful facts
3. package scripts
4. provider/adapter fallback
5. built-in defaults

## 3. Check Current Lane

Run:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py classify-change --workspace-root . --changed-file <path>
```

Read `workflow_lane`:

- `bypass`: do not force guardian flow
- `lightweight`: keep structure, usually no tests
- `full_guardian`: run analyze before edit and finish after edit

## 4. Read Analyze Brief

Default `analyze` output should be short. Check:

- selected seed
- secondary seeds
- lane
- verification budget
- recommended test scope
- must-read paths
- top uncertainty
- next step

If you need full detail, open:

- `.ai/codegraph/summary.json`
- `.ai/codegraph/facts.json`
- `.ai/codegraph/inferences.json`
- `.ai/codegraph/next-action.json`

## 5. Interpret Finish

After `finish`, read:

- `.ai/codegraph/test-results.json`
- `.ai/codegraph/final-state.json`
- `.ai/codegraph/handoff/latest.md`

Do not collapse these states:

- tests passed means the selected commands passed
- directly affected tests found means the graph mapped targeted tests
- baseline red means historical reality may already be failing

## 6. Baseline Red

If baseline was already red:

- `regression_status = no_regression` means the same known failure persisted
- this is not automatically caused by the current edit
- a passing targeted/smoke run can still coexist with a red historical full suite
- do not claim full safety unless the relevant baseline/full verification is green
