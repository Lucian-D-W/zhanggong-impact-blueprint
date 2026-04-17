# Code Impact Guardian Stage 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the stage 1 skill into a more reusable template by adding a generic fallback mode, a minimal TS/JS adapter, and a unified `cig.py` entrypoint without changing the workflow, schema, or edge vocabulary.

**Architecture:** Keep the existing stage 1 scripts as the execution core and add only two thin layers: `adapters.py` for light adapter registration/selection and `cig.py` for command routing. Preserve direct-edge storage, preserve the SQLite schema, and keep Python working exactly as before while adding TS/JS and generic file-level support.

**Tech Stack:** Python 3, SQLite, unittest, coverage.py, Node.js test runner, JSON config, Markdown

---

### Task 1: Lock stage2 behavior with failing tests

**Files:**
- Create: `tests/test_stage2_workflow.py`

- [ ] **Step 1: Add Python regression guard**
- [ ] **Step 2: Add TS/JS minimal end-to-end test**
- [ ] **Step 3: Add generic fallback end-to-end test**
- [ ] **Step 4: Run tests and watch them fail for the expected missing stage2 features**

### Task 2: Add thin adapter support and unified CLI

**Files:**
- Create: `.agents/skills/code-impact-guardian/cig.py`
- Create: `.agents/skills/code-impact-guardian/scripts/adapters.py`
- Modify: `.agents/skills/code-impact-guardian/scripts/build_graph.py`
- Modify: `.agents/skills/code-impact-guardian/scripts/list_seeds.py`
- Modify: `.agents/skills/code-impact-guardian/scripts/generate_report.py`
- Modify: `.agents/skills/code-impact-guardian/scripts/after_edit_update.py`
- Modify: `.code-impact-guardian/config.json`

- [ ] **Step 1: Add adapter selection: auto/python/tsjs/generic**
- [ ] **Step 2: Add generic file-level fallback**
- [ ] **Step 3: Add minimal TS/JS extraction for file/function/test/DEFINES/CALLS/IMPORTS**
- [ ] **Step 4: Add `cig.py` commands: detect/build/seeds/report/after-edit/demo**

### Task 3: Add new fixtures and docs

**Files:**
- Create: `examples/tsjs_minimal/`
- Create: `examples/generic_minimal/`
- Modify: `README.md`
- Modify: `scripts/demo_phase1.py`

- [ ] **Step 1: Add tsjs fixture with real `node --test` execution**
- [ ] **Step 2: Add generic fallback fixture with file-level analysis and a runnable test command**
- [ ] **Step 3: Update README with stage1/stage2 support matrix and copy-into-project instructions**
- [ ] **Step 4: Keep `demo_phase1.py` intact for Python while routing new demos through `cig.py`**

### Task 4: Verify stage2

**Files:**
- Modify runtime artifacts under `.ai/codegraph/`

- [ ] **Step 1: Run stage1 regression test**
- [ ] **Step 2: Run stage2 workflow tests**
- [ ] **Step 3: Run explicit TS/JS and generic demo commands**
- [ ] **Step 4: Inspect resulting SQLite data and reports before claiming completion**
