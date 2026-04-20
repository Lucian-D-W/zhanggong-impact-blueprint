# ZG Impact Blueprint Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight, repo-local skill workflow template that proves the full `build -> report -> edit -> update -> test` safety loop with a Python demo fixture.

**Architecture:** Keep the template flat and copyable. The repo-level skill and three scripts coordinate a SQLite-backed graph, impact reports, git evidence, and a single Python demo fixture. Stage 1 keeps Python-specific logic inside the scripts as the first demonstration chain while preserving configuration points for later adapter extraction.

**Tech Stack:** Python 3, SQLite, unittest, coverage.py, Markdown, git

---

### Task 1: Add failing workflow verification test

**Files:**
- Create: `tests/test_stage1_workflow.py`

- [ ] **Step 1: Write the failing test**

```python
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class Stage1WorkflowTest(unittest.TestCase):
    def test_stage1_demo_generates_db_report_and_results(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        demo_script = repo_root / "scripts" / "demo_phase1.py"
        self.assertTrue(demo_script.exists(), "demo script must exist")

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = pathlib.Path(tmp) / "demo-copy"
            subprocess.run(
                [sys.executable, str(demo_script), "--workspace", str(temp_repo)],
                check=True,
                cwd=repo_root,
            )

            db_path = temp_repo / ".ai" / "codegraph" / "codegraph.db"
            report_path = temp_repo / ".ai" / "codegraph" / "reports" / "impact-demo-login-impact.md"
            test_results = temp_repo / ".ai" / "codegraph" / "test-results.json"

            self.assertTrue(db_path.exists())
            self.assertTrue(report_path.exists())
            self.assertTrue(test_results.exists())

            with sqlite3.connect(db_path) as conn:
                node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                self.assertGreater(node_count, 0)
                self.assertGreater(edge_count, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_stage1_workflow -v`
Expected: FAIL because `scripts/demo_phase1.py` and the workflow files do not exist yet.

- [ ] **Step 3: Implement the minimum files needed to make this test meaningful**

Create the stage 1 template files, demo script, and example fixture so the test can start exercising real workflow behavior.

- [ ] **Step 4: Run the test again and continue until it passes**

Run: `python -m unittest tests.test_stage1_workflow -v`
Expected: PASS

### Task 2: Build the stage 1 workflow template

**Files:**
- Create: `AGENTS.md`
- Create: `.agents/skills/zhanggong-impact-blueprint/SKILL.md`
- Create: `.agents/skills/zhanggong-impact-blueprint/scripts/build_graph.py`
- Create: `.agents/skills/zhanggong-impact-blueprint/scripts/generate_report.py`
- Create: `.agents/skills/zhanggong-impact-blueprint/scripts/after_edit_update.py`
- Create: `.zhanggong-impact-blueprint/config.yaml`
- Create: `.zhanggong-impact-blueprint/schema.sql`
- Create: `README.md`
- Create: `examples/python_minimal/README.md`
- Create: `examples/python_minimal/src/app.py`
- Create: `examples/python_minimal/src/session.py`
- Create: `examples/python_minimal/tests/test_app.py`
- Create: `examples/python_minimal/docs/rules/auth-session.md`
- Create: `scripts/demo_phase1.py`

- [ ] **Step 1: Implement graph build**

Support Python fixture discovery and emit:
- file, function, test, rule nodes
- DEFINES, CALLS, IMPORTS, COVERS, GOVERNS direct edges
- git evidence rows

- [ ] **Step 2: Implement impact report generation**

Generate Markdown report from a seed, computing transitive CALLS and IMPORTS in memory/query time only.

- [ ] **Step 3: Implement after-edit update**

Refresh graph, append post-change notes, run coverage-backed tests, and write test result artifacts.

- [ ] **Step 4: Document usage**

Document that Python is only the first demonstration chain, not a product binding, and that future TS/JS support extends config and adapters later without replacing the core workflow.

### Task 3: Verify the full demo end-to-end

**Files:**
- Modify: `.ai/codegraph/*` runtime artifacts

- [ ] **Step 1: Run the demo**

Run: `python scripts/demo_phase1.py`
Expected: creates database, report, build log, test results, and coverage output.

- [ ] **Step 2: Inspect outputs**

Confirm:
- SQLite contains nodes and edges
- report contains direct and transitive sections
- test results record exit code and coverage status

- [ ] **Step 3: Re-run verification test**

Run: `python -m unittest tests.test_stage1_workflow -v`
Expected: PASS

