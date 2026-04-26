# ZG Impact Blueprint Quickstart

ZG Impact Blueprint is a low-friction workflow harness. It should help real work move faster, not make every edit feel heavy.

## Install GitNexus First

```bash
npm install -g gitnexus
gitnexus --version
```

Use `zhanggong` as the daily entrypoint after GitNexus is installed. GitNexus is the primary graph fact source when ready, not the workflow owner. Avoid bare `gitnexus analyze` for normal runs; zhanggong suppresses root-file side effects and records provider authority.

## Minimal First Run

Preview first, then write the minimal runtime files:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root . --dry-run --preview-changes
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root .
```

Minimal setup writes only:

- `.zhanggong-impact-blueprint/config.json`
- `.zhanggong-impact-blueprint/schema.sql`
- `.ai/codegraph/`
- managed `.gitignore` block

Use `setup --full` only when you explicitly want:

- `AGENTS.md` managed block
- `QUICKSTART.md`
- `TROUBLESHOOTING.md`
- `CONSUMER_GUIDE.md`

## Choose The Right Lane

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py classify-change --workspace-root . --changed-file <path>
```

Read `workflow_lane`:

- `bypass`: ordinary docs, archive notes, diagrams, review prose. Do not run full guardian.
- `lightweight`: agent/workflow/process docs. Keep structure, usually no tests.
- `full_guardian`: source, tests, config, schema, SQL, env, dependencies, rules, command behavior.

Mixed changes use the highest lane needed by any file.

## Daily Full Guardian Flow

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py health --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file <path>
python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted
```

`analyze` prints a short brief by default. Read it first.

## Output Layers

- `.ai/codegraph/summary.json`: first-glance action summary
- `.ai/codegraph/facts.json`: observed repo facts only
- `.ai/codegraph/inferences.json`: uncertainty, fallback, trust, low-confidence hints
- `.ai/codegraph/next-action.json`: agent control plane
- `.ai/codegraph/reports/*.json`: full impact data
- `.ai/codegraph/final-state.json`: finish outcome
- `.ai/codegraph/handoff/latest.md`: handoff note

Use `--json` or `--full-json` only when a script needs the full payload.

## Multi-Entry Analyze

For broad or multi-entry changes, `analyze` should expose:

- `selected_seed`: primary view
- `secondary_seeds`: parallel entry points
- `seed_coverage`: why that choice is acceptable

It should only require manual selection when the candidate set is too broad to continue honestly.

## Test Reality

`finish` interprets test results with baseline reality:

- tests passed means the selected commands passed
- directly affected tests found means the graph mapped targeted tests
- no directly affected tests plus passing suite usually means no obvious regression, not targeted coverage
- baseline red can be historical repo reality, not this edit

## Calibration Priority

Test command and adapter choice follow real repo facts:

1. repo config
2. recent successful command
3. package scripts
4. provider/adapter fallback
5. built-in defaults

If the selected test command looks wrong, run `calibrate` and inspect `test_command_candidates`, `ignored_test_commands`, and `test_command_reason`.

Default `finish` is current-task verification. Broad Python `unittest discover` is skipped when no current-task test is mapped; use `--test-scope full` only when you intentionally want historical/baseline verification.
