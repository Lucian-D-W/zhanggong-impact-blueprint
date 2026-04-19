# Code Impact Guardian Working Agreement

This repository uses Code Impact Guardian as a repo-local workflow template.

Whenever a task changes code, behavior, configuration, schema, or tests:

1. Run `cig.py setup` automatically if `.code-impact-guardian/config.json` is missing
2. Run `cig.py analyze`
3. Read the impact report
4. Only then allow code edits
5. After edits, run `cig.py finish`

## Guardrails

- Persist only direct edges.
- Never persist indirect or transitive impact as durable graph truth.
- Compute transitive impact only while generating the report.
- If coverage is unavailable, record that fact. Never fabricate coverage-backed results.
- Delete actions must move items to the recycle bin or trash by default. Permanent deletion requires explicit, strict user approval first.
- Tests passed is not the same thing as safe.
- If `analyze` says the report is incomplete, do not treat that as edit-safe context unless the user explicitly overrides it.
- Local markdown rules remain the default rule source.
- If a command fails, check `.ai/codegraph/logs/` and `TROUBLESHOOTING.md` before retrying.
