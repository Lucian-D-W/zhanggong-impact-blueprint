# Stage 11 Follow-up Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely fix the two post-stage11 reliability gaps: workspace-misdirected recovery commands and delete-only changes being treated as missing context.

**Architecture:** Keep the repair narrow. First tighten regression tests around recovery command targeting and delete-aware context inference, then implement a shared workspace-aware recovery-command formatter and a deletion-aware diff parser that prefers honest partial context over false certainty. Preserve existing stage10/stage11 behavior everywhere else.

**Tech Stack:** Python 3, unittest, PowerShell, git diff parsing, JSON error payloads

---

### Task 1: Baseline And Impact Guard

**Files:**
- Read: `AGENTS.md`
- Read: `.agents/skills/zhanggong-impact-blueprint/SKILL.md`
- Read: `.agents/skills/zhanggong-impact-blueprint/cig.py`
- Read: `.agents/skills/zhanggong-impact-blueprint/scripts/runtime_support.py`
- Read: `.agents/skills/zhanggong-impact-blueprint/scripts/context_inference.py`
- Read: `.agents/skills/zhanggong-impact-blueprint/scripts/build_graph.py`
- Modify later: runtime artifacts under `.ai/codegraph/`

- [ ] **Step 1: Capture a clean pre-change baseline**

Run:

```powershell
git status --short
python -m unittest tests.test_stage10_workflow -v
python -m unittest tests.test_stage11_workflow -v
```

Expected:
- working tree shows no source edits that would collide with the fix
- stage10 and stage11 tests pass before any changes

- [ ] **Step 2: Run the repo-local guard flow before touching source or tests**

Run:

```powershell
python .agents/skills/zhanggong-impact-blueprint/scripts/build_graph.py --workspace-root . --config .zhanggong-impact-blueprint/config.json
python .agents/skills/zhanggong-impact-blueprint/scripts/generate_report.py --workspace-root . --config .zhanggong-impact-blueprint/config.json --task-id stage11-followup-plan --seed fn:src/app.py:login
```

Expected:
- graph/report artifacts exist
- report is readable and not empty
- implementation can proceed without violating the repo working agreement

### Task 2: Lock Workspace-Scoped Recovery Behavior With Tests

**Files:**
- Modify: `tests/test_stage11_workflow.py`

- [ ] **Step 1: Add a regression test for `health` fix commands targeting the requested workspace**

Test shape:

```python
def test_health_fix_commands_target_requested_workspace(self):
    ...
    payload = run_json([... "health", "--workspace-root", str(repo_root)], cwd=repo_root)
    joined = " ".join(payload["fix_commands"])
    self.assertIn(str(repo_root), joined)
    self.assertNotIn("--workspace-root .", joined)
```

- [ ] **Step 2: Tighten the existing `CONTEXT_MISSING` recovery-command test**

Test shape:

```python
def test_context_missing_writes_workspace_scoped_recovery_commands(self):
    ...
    self.assertIn(str(repo_root), " ".join(last_error["recovery_commands"]))
    self.assertNotIn("--workspace-root .", " ".join(last_error["recovery_commands"]))
```

- [ ] **Step 3: Tighten the existing build-lock recovery-command test**

Test shape:

```python
def test_build_lock_surfaces_workspace_scoped_recovery_commands(self):
    ...
    joined = " ".join(last_error["recovery_commands"])
    self.assertIn(str(repo_root), joined)
    self.assertNotIn("status --workspace-root .", joined)
```

- [ ] **Step 4: Run only the new recovery tests and confirm they fail for the current bug**

Run:

```powershell
python -m unittest tests.test_stage11_workflow.Stage11WorkflowTest.test_context_missing_writes_machine_recovery_commands -v
python -m unittest tests.test_stage11_workflow.Stage11WorkflowTest.test_health_command_reports_read_only_recovery_state -v
python -m unittest tests.test_stage11_workflow.Stage11WorkflowTest.test_build_lock_surfaces_recovery_commands -v
```

Expected:
- at least one assertion fails because commands still target `.`

### Task 3: Lock Delete-Only Context Handling With Tests

**Files:**
- Modify: `tests/test_stage11_workflow.py`

- [ ] **Step 1: Add a delete-only working-tree regression test**

Test shape:

```python
def test_delete_only_change_is_not_reported_as_context_missing(self):
    ...
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    ...
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo_root, check=True, capture_output=True, text=True)
    (repo_root / "src" / "app.py").unlink()
    result = subprocess.run([... "analyze", "--workspace-root", str(repo_root)], ...)
    self.assertNotIn("CONTEXT_MISSING", result.stderr)
```

- [ ] **Step 2: Assert the system degrades honestly instead of fabricating certainty**

Test shape:

```python
payload = json.loads((repo_root / ".ai" / "codegraph" / "context-resolution.json").read_text(encoding="utf-8"))
self.assertIn("src/app.py", payload.get("changed_files", []))
self.assertIn(payload.get("context_status"), {"partial", "resolved"})
```

- [ ] **Step 3: Allow the final expectation to be low-confidence if no exact live seed exists**

Acceptance rule for the test:
- acceptable outcomes are file-level fallback, partial context, or an explicit lower-confidence path
- unacceptable outcome is a bare `CONTEXT_MISSING` despite a real deletion in git diff

- [ ] **Step 4: Run the new delete-only test and confirm it fails before implementation**

Run:

```powershell
python -m unittest tests.test_stage11_workflow.Stage11WorkflowTest.test_delete_only_change_is_not_reported_as_context_missing -v
```

Expected:
- current implementation fails with `CONTEXT_MISSING`

### Task 4: Implement Workspace-Aware Recovery Commands

**Files:**
- Modify: `.agents/skills/zhanggong-impact-blueprint/cig.py`
- Modify: `.agents/skills/zhanggong-impact-blueprint/scripts/runtime_support.py`
- Modify: `.agents/skills/zhanggong-impact-blueprint/scripts/build_graph.py`

- [ ] **Step 1: Add one shared formatter for direct-execution recovery commands**

Implementation target:
- centralize command construction so `health`, `CONTEXT_MISSING`, and build-lock paths all use the same workspace-root formatting
- prefer the actual `workspace_root` string over `.`
- preserve direct executability for weak models

- [ ] **Step 2: Update `health_payload()` to emit workspace-scoped `fix_commands` and `next_command`**

Acceptance:
- every returned command points at the inspected workspace, not the caller cwd

- [ ] **Step 3: Update `CONTEXT_MISSING` recovery generation to use the same formatter**

Acceptance:
- first recovery command remains directly runnable
- placeholder commands remain available as alternatives, but the workspace target is explicit

- [ ] **Step 4: Update build-lock and related recovery paths to use the same formatter**

Acceptance:
- lock recovery no longer suggests `status --workspace-root .`

- [ ] **Step 5: Run the targeted recovery tests until they pass**

Run:

```powershell
python -m unittest tests.test_stage11_workflow.Stage11WorkflowTest.test_context_missing_writes_machine_recovery_commands -v
python -m unittest tests.test_stage11_workflow.Stage11WorkflowTest.test_health_command_reports_read_only_recovery_state -v
python -m unittest tests.test_stage11_workflow.Stage11WorkflowTest.test_build_lock_surfaces_recovery_commands -v
```

Expected:
- all three pass

### Task 5: Implement Delete-Aware Context Inference

**Files:**
- Modify: `.agents/skills/zhanggong-impact-blueprint/scripts/context_inference.py`
- Modify: `.agents/skills/zhanggong-impact-blueprint/cig.py`

- [ ] **Step 1: Extend unified-diff parsing to retain deleted paths**

Implementation target:
- when a diff pair is `--- a/path` and `+++ /dev/null`, keep `path` in `changed_files`
- record deletion line information conservatively if exact added-line mapping is impossible

- [ ] **Step 2: Preserve honest uncertainty for delete-only changes**

Implementation target:
- if a deleted file no longer has a live function seed, keep context as partial/low-confidence rather than pretending context is complete
- do not fabricate a function seed solely to satisfy the flow

- [ ] **Step 3: Make `analyze` treat delete-only context as real context**

Implementation target:
- prefer file-level or low-confidence continuation paths over `CONTEXT_MISSING`
- keep recovery commands available if an explicit seed is still required later

- [ ] **Step 4: Run the delete-only regression test until it passes**

Run:

```powershell
python -m unittest tests.test_stage11_workflow.Stage11WorkflowTest.test_delete_only_change_is_not_reported_as_context_missing -v
```

Expected:
- test passes without regressing trust honesty

### Task 6: Full Verification And Closeout

**Files:**
- Modify runtime artifacts under `.ai/codegraph/`

- [ ] **Step 1: Run the focused workflow suites**

Run:

```powershell
python -m unittest tests.test_stage10_workflow -v
python -m unittest tests.test_stage11_workflow -v
```

Expected:
- both pass

- [ ] **Step 2: Run the full workflow regression suite**

Run:

```powershell
python -m unittest discover -s tests -p "test_*_workflow.py" -v
```

Expected:
- full suite passes

- [ ] **Step 3: Run the post-edit repo-local guard flow**

Run:

```powershell
python .agents/skills/zhanggong-impact-blueprint/scripts/after_edit_update.py --workspace-root . --config .zhanggong-impact-blueprint/config.json --task-id stage11-followup-plan --seed fn:src/app.py:login --changed-file .agents/skills/zhanggong-impact-blueprint/cig.py
```

Expected:
- post-edit artifacts refresh successfully
- no hidden runtime error is introduced by the follow-up changes

- [ ] **Step 4: Inspect final evidence before claiming completion**

Checklist:
- recovery commands always target the inspected workspace
- delete-only diffs no longer collapse to `CONTEXT_MISSING`
- no stage10/stage11 regression
- no unrelated refactor slipped in

