# Stage 17 Changelog

## Final Atlas Polish & Reliability Closure

Stage 17 closes the Stage 16 contract atlas into a final product-shaped skill.

## Scope decisions

Stage 17 intentionally does not add:

- LSP integration
- runtime trace or profiling
- CI history learning
- embedding or semantic search
- more aggressive automatic seed selection
- automatic planner behavior that decides for the agent

## Reliability fixes

- Added `scripts/db_support.py` and moved SQLite access to an explicit close path.
- Replaced implicit `sqlite3.connect(...)` context-manager usage with explicit connection lifecycle handling across CLI, graph, report, finish, and loop helpers.
- Updated tests that opened SQLite directly so they also close explicitly.
- Added strict `ResourceWarning` coverage for repeated-failure and graph-query scenarios.
- Added smoke coverage to ensure key CLI commands exit cleanly with timeout protection.

## Agent Atlas changes

- Added `atlas_views` to report and next-action payloads.
- Added `atlas_summary` for presentation compression without deleting full facts.
- Added view types:
  - `bilateral_contract`
  - `page_flow`
  - `data_flow`
  - `config_surface`
  - `uncertainty`
- Added compression so brief layers show the highest-signal views first while preserving complete `affected_contracts` in JSON output.
- Updated `next-action` text to become reading guidance instead of system-made plans.

## Repair loop changes

- Repeated-failure loop breaker now widens reading scope, not just test scope.
- Added `loop_atlas_views` to `loop-breaker-report.json`.
- Added explicit uncertainty surfacing by retry count.
- Added `stop_local_patching_reason` at higher retry counts.

## Release hygiene

- Added `release-check` CLI command.
- Added detection for:
  - private names
  - absolute user paths
  - temp-path leaks
  - token-like secrets
  - stale public-skill stage text
  - `config.local.json`
  - `.ai/codegraph` runtime artifacts
- Tightened single-folder export so runtime artifacts and private config files are excluded by default.

## Documentation closure

- Reframed `README.md` from stage-progress narrative into product documentation.
- Updated `AGENTS.md` to reflect final atlas reading rules and repeated-failure behavior.
- Updated `.agents/skills/zhanggong-impact-blueprint/SKILL.md` with final boundary, atlas reading order, and uncertainty handling.
- Added the Stage 17 reviewer guide, now archived at `docs/archive/STAGE17_REVIEW_GUIDE.md`, for validation.

