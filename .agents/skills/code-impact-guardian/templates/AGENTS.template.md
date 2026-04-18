# Code Impact Guardian Working Agreement

This repository uses Code Impact Guardian as a repo-local workflow template.

Whenever a task changes code, behavior, configuration, schema, or tests:

1. Run `cig.py build`
2. Run `cig.py report`
3. Read the impact report
4. Only then allow code edits
5. After edits, run `cig.py after-edit`

## Guardrails

- Persist only direct edges.
- Never persist indirect or transitive impact as durable graph truth.
- Compute transitive impact only while generating the report.
- If coverage is unavailable, record that fact. Never fabricate coverage-backed results.
- Local markdown rules remain the default rule source.
- If a command fails, check `.ai/codegraph/logs/` and `TROUBLESHOOTING.md` before retrying.
