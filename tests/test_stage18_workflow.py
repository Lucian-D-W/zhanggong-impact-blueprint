import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests.test_stage7_workflow import copy_single_skill_folder, run_json


NEW_SKILL_SLUG = "zhanggong-impact-blueprint"
NEW_STATE_DIR = ".zhanggong-impact-blueprint"
NEW_DISPLAY_NAME = "ZG Impact Blueprint"
NEW_FORMAL_NAME = "张工的施工图 / ZhangGong Impact Blueprint"
OLD_SKILL_SLUG = "code-impact-guardian"
OLD_STATE_DIR = ".code-impact-guardian"


def load_cig_module(repo_root: pathlib.Path):
    module_path = repo_root / ".agents" / "skills" / NEW_SKILL_SLUG / "cig.py"
    spec = importlib.util.spec_from_file_location("guardian_cig_stage18", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Stage18WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = pathlib.Path(__file__).resolve().parents[1]
        cls.cig_script = cls.repo_root / ".agents" / "skills" / NEW_SKILL_SLUG / "cig.py"

    def test_skill_frontmatter_and_identity_constants_match_final_slug(self):
        skill_path = self.repo_root / ".agents" / "skills" / NEW_SKILL_SLUG / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        self.assertIn(f"name: {NEW_SKILL_SLUG}", text)
        self.assertIn(NEW_DISPLAY_NAME, text)

        cig = load_cig_module(self.repo_root)
        self.assertEqual(cig.SKILL_SLUG, NEW_SKILL_SLUG)
        self.assertEqual(cig.SKILL_DIRNAME, NEW_SKILL_SLUG)
        self.assertEqual(cig.STATE_DIRNAME, NEW_STATE_DIR)
        self.assertEqual(cig.DISPLAY_NAME, NEW_DISPLAY_NAME)
        self.assertEqual(cig.FORMAL_NAME, NEW_FORMAL_NAME)

    def test_consumer_export_uses_new_identity_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            consumer_export = pathlib.Path(tmp) / "consumer-export"
            payload = run_json(
                [
                    sys.executable,
                    str(self.cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(self.repo_root),
                    "--out",
                    str(consumer_export),
                    "--mode",
                    "consumer",
                ],
                cwd=self.repo_root,
            )
            self.assertEqual(payload["mode"], "consumer")
            self.assertTrue((consumer_export / ".agents" / "skills" / NEW_SKILL_SLUG / "SKILL.md").exists())
            self.assertTrue((consumer_export / NEW_STATE_DIR / "config.template.json").exists())
            self.assertFalse((consumer_export / ".agents" / "skills" / OLD_SKILL_SLUG).exists())
            self.assertFalse((consumer_export / OLD_STATE_DIR).exists())

    def test_single_folder_export_root_uses_new_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            single_export = pathlib.Path(tmp) / "single-folder-export"
            payload = run_json(
                [
                    sys.executable,
                    str(self.cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(self.repo_root),
                    "--out",
                    str(single_export),
                    "--mode",
                    "single-folder",
                ],
                cwd=self.repo_root,
            )
            self.assertEqual(payload["mode"], "single-folder")
            self.assertTrue((single_export / NEW_SKILL_SLUG / "cig.py").exists())
            self.assertFalse((single_export / OLD_SKILL_SLUG).exists())

    def test_setup_writes_new_state_dir_and_not_old_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            single_export = pathlib.Path(tmp) / "single-folder-export"
            run_json(
                [
                    sys.executable,
                    str(self.cig_script),
                    "export-skill",
                    "--workspace-root",
                    str(self.repo_root),
                    "--out",
                    str(single_export),
                    "--mode",
                    "single-folder",
                ],
                cwd=self.repo_root,
            )

            repo_root = pathlib.Path(tmp) / "consumer-repo"
            repo_cig = copy_single_skill_folder(single_export, repo_root)
            (repo_root / "src").mkdir(parents=True, exist_ok=True)
            (repo_root / "src" / "app.py").write_text("def ping():\n    return 'pong'\n", encoding="utf-8")
            (repo_root / "tests").mkdir(parents=True, exist_ok=True)
            (repo_root / "tests" / "test_app.py").write_text(
                "from src.app import ping\n\n\ndef test_ping():\n    assert ping() == 'pong'\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_cig),
                    "setup",
                    "--workspace-root",
                    str(repo_root),
                    "--project-root",
                    ".",
                    "--profile",
                    "python-basic",
                ],
                cwd=repo_root,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertTrue((repo_root / NEW_STATE_DIR / "config.json").exists())
            self.assertTrue((repo_root / NEW_STATE_DIR / "schema.sql").exists())
            self.assertFalse((repo_root / OLD_STATE_DIR / "config.json").exists())

    def test_public_docs_use_new_name_and_new_paths(self):
        readme = (self.repo_root / "README.md").read_text(encoding="utf-8")
        agents = (self.repo_root / "AGENTS.md").read_text(encoding="utf-8")
        skill = (self.repo_root / ".agents" / "skills" / NEW_SKILL_SLUG / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn(NEW_FORMAL_NAME, readme)
        self.assertIn(NEW_DISPLAY_NAME, skill)
        self.assertIn(NEW_DISPLAY_NAME, agents)

        for text in (readme, agents, skill):
            self.assertIn(NEW_SKILL_SLUG, text)
            self.assertNotIn(OLD_SKILL_SLUG, text)
            self.assertNotIn(OLD_STATE_DIR, text)

    def test_active_repo_surface_has_no_old_identity_residue(self):
        scan_roots = [
            self.repo_root / ".agents" / "skills" / NEW_SKILL_SLUG,
            self.repo_root / NEW_STATE_DIR,
            self.repo_root / "tests",
            self.repo_root / "scripts",
            self.repo_root / "docs" / "archive" / "STAGE17_CHANGELOG.md",
            self.repo_root / "docs" / "archive" / "STAGE17_REVIEW_GUIDE.md",
            self.repo_root / "docs" / "demo",
            self.repo_root / "docs" / "superpowers" / "plans",
            self.repo_root / "README.md",
            self.repo_root / "AGENTS.md",
            self.repo_root / "mainstone.md",
        ]

        allowed_old_identity_files = {self.repo_root / "tests" / "test_stage18_workflow.py"}
        text_suffixes = {".md", ".py", ".json", ".yaml", ".yml", ".sql", ".txt"}

        for root in scan_roots:
            if root.is_dir():
                for path in root.rglob("*"):
                    self.assertNotIn(OLD_SKILL_SLUG, path.as_posix())
                    self.assertNotIn(OLD_STATE_DIR, path.as_posix())
                    if path.is_file() and path.suffix in text_suffixes:
                        if path in allowed_old_identity_files:
                            continue
                        text = path.read_text(encoding="utf-8")
                        self.assertNotIn(OLD_SKILL_SLUG, text, str(path))
                        self.assertNotIn(OLD_STATE_DIR, text, str(path))
            else:
                self.assertNotIn(OLD_SKILL_SLUG, root.as_posix())
                self.assertNotIn(OLD_STATE_DIR, root.as_posix())
                text = root.read_text(encoding="utf-8")
                self.assertNotIn(OLD_SKILL_SLUG, text, str(root))
                self.assertNotIn(OLD_STATE_DIR, text, str(root))

        self.assertFalse((self.repo_root / "STAGE17_CHANGELOG.md").exists())
        self.assertFalse((self.repo_root / "STAGE17_REVIEW_GUIDE.md").exists())


if __name__ == "__main__":
    unittest.main()

