# Changelog

## v0.18.1-rc1

Release status: `Stage 18.1 accepted candidate`

Accepted for the Stage 18 user-feedback blocker scope.
Historical full regression was intentionally out of scope for this hotfix.

### User-visible fixes

- fixed the Windows `.sh` preflight miss so Windows users are warned before `finish` tries to run an unusable shell script
- fixed the GBK/Windows terminal case where tests could pass but CLI JSON output still failed on unicode rendering
- added first-class support for Python repositories that keep tests under `test/` instead of `tests/`
- fixed flaky baseline/no-regression comparison by normalizing unstable failure output before computing the signature
- fixed stale `handoff/latest.md` failure content after a later successful `finish`
- fixed seed-selection mode so `next-action.json` no longer recommends `finish` before a seed is chosen
- fixed trust explanations that could contradict the trust axes
- fixed repo-local list-form `test_command` values so explicit commands such as `["node", "--test"]` are respected

### Acceptance evidence kept with this release candidate

- `tests.test_stage18_workflow`: `26/26 OK`
- `tests.test_stage18_1_workflow`: `23/23 OK`
- baseline stability repeat: `10x OK`
- GBK smoke: `OK`
- CLI smoke: `OK`

### Scope boundary

- no new features were added in this release-prep round
- no graph expansion was added
- no old-stage full discover or full historical regression was run
- any new issue outside the Stage 18.1 blocker set should go to Stage 18.2 or backlog
