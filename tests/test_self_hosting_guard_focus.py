import json
import importlib.util
import pathlib
import shutil
import subprocess
import tempfile
import unittest

sys_path_root = pathlib.Path(__file__).resolve().parents[1] / ".agents" / "skills" / "zhanggong-impact-blueprint" / "scripts"
import sys

if str(sys_path_root) not in sys.path:
    sys.path.insert(0, str(sys_path_root))

from adapters import detect_primary_adapter  # noqa: E402
from build_graph import project_root_for  # noqa: E402
from parser_backends import iter_matching_files  # noqa: E402


def load_repo_config(repo_root: pathlib.Path) -> dict:
    return json.loads((repo_root / ".zhanggong-impact-blueprint" / "config.json").read_text(encoding="utf-8"))


def load_cig_module(repo_root: pathlib.Path):
    module_path = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint" / "cig.py"
    spec = importlib.util.spec_from_file_location("guardian_cig", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SelfHostingGuardFocusTest(unittest.TestCase):
    def test_repo_local_config_targets_guardian_repo_root(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        config = load_repo_config(repo_root)

        self.assertEqual(config["project_root"], ".")
        self.assertEqual(config["primary_adapter"], "python")
        self.assertIn("scripts/*.py", config["python"]["source_globs"])
        self.assertIn("scripts/**/*.py", config["python"]["source_globs"])
        self.assertIn(".agents/skills/zhanggong-impact-blueprint/*.py", config["python"]["source_globs"])
        self.assertIn(".agents/skills/zhanggong-impact-blueprint/**/*.py", config["python"]["source_globs"])
        self.assertEqual(project_root_for(repo_root, config), repo_root.resolve())

    def test_self_host_globs_ignore_nested_dist_copies(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        config = load_repo_config(repo_root)

        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = pathlib.Path(tmp) / "guardian-self-host"
            skill_source = repo_root / ".agents" / "skills" / "zhanggong-impact-blueprint"
            skill_target = workspace_root / ".agents" / "skills" / "zhanggong-impact-blueprint"
            skill_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill_source, skill_target)

            (workspace_root / "scripts").mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo_root / "scripts" / "demo_phase1.py", workspace_root / "scripts" / "demo_phase1.py")
            (workspace_root / "tests").mkdir(parents=True, exist_ok=True)
            (workspace_root / "tests" / "test_guard_focus.py").write_text(
                "def test_guard_focus():\n"
                "    assert True\n",
                encoding="utf-8",
            )

            dist_skill_target = workspace_root / "dist" / "zhanggong-impact-blueprint-stage1-review-v2" / ".agents" / "skills" / "zhanggong-impact-blueprint"
            dist_skill_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill_target, dist_skill_target)
            dist_scripts = workspace_root / "dist" / "zhanggong-impact-blueprint-stage1-review-v2" / "scripts"
            dist_scripts.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workspace_root / "scripts" / "demo_phase1.py", dist_scripts / "demo_phase1.py")
            dist_tests = workspace_root / "dist" / "zhanggong-impact-blueprint-stage1-review-v2" / "tests"
            dist_tests.mkdir(parents=True, exist_ok=True)
            (dist_tests / "test_guard_focus.py").write_text(
                "def test_guard_focus():\n"
                "    assert False\n",
                encoding="utf-8",
            )

            source_matches = [
                path.relative_to(workspace_root).as_posix()
                for path in iter_matching_files(workspace_root, config["python"]["source_globs"])
            ]
            test_matches = [
                path.relative_to(workspace_root).as_posix()
                for path in iter_matching_files(workspace_root, config["python"]["test_globs"])
            ]

            self.assertIn(".agents/skills/zhanggong-impact-blueprint/cig.py", source_matches)
            self.assertIn(".agents/skills/zhanggong-impact-blueprint/scripts/parser_backends.py", source_matches)
            self.assertIn("scripts/demo_phase1.py", source_matches)
            self.assertNotIn("dist/zhanggong-impact-blueprint-stage1-review-v2/.agents/skills/zhanggong-impact-blueprint/cig.py", source_matches)
            self.assertNotIn(
                "dist/zhanggong-impact-blueprint-stage1-review-v2/.agents/skills/zhanggong-impact-blueprint/scripts/parser_backends.py",
                source_matches,
            )
            self.assertNotIn("dist/zhanggong-impact-blueprint-stage1-review-v2/scripts/demo_phase1.py", source_matches)
            self.assertIn("tests/test_guard_focus.py", test_matches)
            self.assertNotIn("dist/zhanggong-impact-blueprint-stage1-review-v2/tests/test_guard_focus.py", test_matches)
            self.assertEqual(detect_primary_adapter(workspace_root, config), "python")

    def test_copy_template_omits_repo_local_config(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        cig = load_cig_module(repo_root)

        with tempfile.TemporaryDirectory() as tmp:
            source_root = pathlib.Path(tmp) / "source"
            destination_root = pathlib.Path(tmp) / "destination"
            (source_root / ".zhanggong-impact-blueprint").mkdir(parents=True, exist_ok=True)
            (source_root / "scripts").mkdir(parents=True, exist_ok=True)
            (source_root / ".zhanggong-impact-blueprint" / "config.json").write_text('{"project_root":"."}\n', encoding="utf-8")
            (source_root / "scripts" / "demo_phase1.py").write_text("print('demo')\n", encoding="utf-8")

            cig.copy_template(source_root, destination_root)

            self.assertFalse((destination_root / ".zhanggong-impact-blueprint" / "config.json").exists())
            self.assertTrue((destination_root / "scripts" / "demo_phase1.py").exists())

    def test_in_place_demo_keeps_self_hosting_config(self):
        repo_root = pathlib.Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as tmp:
            temp_repo = pathlib.Path(tmp) / "guardian-copy"
            ignore = shutil.ignore_patterns(".git", ".ai", "__pycache__", "*.pyc", "dist", "*.zip")
            shutil.copytree(repo_root, temp_repo, ignore=ignore)

            demo_script = temp_repo / "scripts" / "demo_phase1.py"
            subprocess.run([sys.executable, str(demo_script)], cwd=temp_repo, check=True)

            config = json.loads((temp_repo / ".zhanggong-impact-blueprint" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["project_root"], ".")
            self.assertTrue((temp_repo / ".ai" / "codegraph" / "test-results.json").exists())

