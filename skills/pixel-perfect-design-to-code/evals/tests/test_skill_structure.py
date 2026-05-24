from __future__ import annotations

import unittest
from pathlib import Path

from eval_suite import load_pixel_eval_module


ROOT = Path(__file__).resolve().parents[4]
SKILLS = ROOT / "skills"
SKILL_WORKSPACE = ROOT / "skills" / "pixel-perfect-design-to-code"
SKILL_BUNDLES = SKILL_WORKSPACE / "skills"
SKILL = SKILL_BUNDLES / "pixel-perfect-design-to-code"
PIXEL_EVALS = SKILL_WORKSPACE / "evals"


class SkillStructureTests(unittest.TestCase):
    def test_skills_collection_has_index(self) -> None:
        index = SKILLS / "README.md"

        self.assertTrue(index.is_file())
        text = index.read_text(encoding="utf-8")
        skill_dirs = sorted(
            bundle
            for workspace in SKILLS.iterdir()
            if workspace.is_dir() and (workspace / "skills").is_dir()
            for bundle in (workspace / "skills").iterdir()
            if (bundle / "SKILL.md").is_file()
        )

        self.assertIn("pixel-perfect-design-to-code", text)
        self.assertGreaterEqual(len(skill_dirs), 1)
        for skill_dir in skill_dirs:
            with self.subTest(skill=skill_dir.name):
                self.assertIn(skill_dir.name, text)

    def test_skill_bundle_uses_standard_agent_skills_layout(self) -> None:
        self.assertTrue((SKILL / "SKILL.md").is_file())
        self.assertTrue((SKILL / "agents" / "pixel-spark-explorer.toml").is_file())
        self.assertTrue((SKILL / "agents" / "pixel-spark-worker.toml").is_file())
        self.assertTrue((SKILL / "agents" / "pixel-smart-reviewer.toml").is_file())
        self.assertTrue((SKILL / "scripts" / "opencv_diff_boxes.py").is_file())
        self.assertTrue((SKILL / "scripts" / "goal_report.py").is_file())
        self.assertTrue((SKILL / "references" / "layers.md").is_file())
        self.assertTrue((SKILL / "references" / "goal-loop.md").is_file())
        self.assertTrue((SKILL / "references" / "subagents.md").is_file())
        self.assertTrue((SKILL / "assets" / "grid-overlays").is_dir())
        self.assertFalse((ROOT / "examples").exists())

    def test_eval_suites_are_nested_by_skill(self) -> None:
        self.assertTrue(SKILL_BUNDLES.is_dir())
        self.assertTrue(SKILL.is_dir())
        self.assertTrue((SKILL_WORKSPACE / "evals").is_dir())
        self.assertTrue((PIXEL_EVALS / "cases.json").is_file())
        self.assertTrue((PIXEL_EVALS / "run_evals.py").is_file())
        self.assertTrue((PIXEL_EVALS / "run_codex_exec.py").is_file())
        self.assertTrue((PIXEL_EVALS / "workflow.py").is_file())
        self.assertTrue((PIXEL_EVALS / "tests").is_dir())
        self.assertFalse((ROOT / "evals").exists())
        self.assertFalse((ROOT / "tests").exists())

    def test_nested_eval_suite_scripts_are_loadable(self) -> None:
        run_codex_exec = load_pixel_eval_module("run_codex_exec")
        run_evals = load_pixel_eval_module("run_evals")

        self.assertEqual(PIXEL_EVALS / "run_codex_exec.py", Path(run_codex_exec.__file__))
        self.assertEqual(PIXEL_EVALS / "run_evals.py", Path(run_evals.__file__))

    def test_skill_instructions_use_paths_relative_to_skill_root(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                SKILL / "SKILL.md",
                SKILL / "references" / "goal-loop.md",
                SKILL / "scripts" / "opencv_diff_boxes.py",
            )
        )

        self.assertNotIn("skills/pixel-perfect-design-to-code/scripts", text)
        self.assertIn("scripts/opencv_diff_boxes.py", text)
        self.assertIn("scripts/goal_report.py", text)

    def test_bundled_spark_agents_keep_model_lock_and_scope(self) -> None:
        explorer = (SKILL / "agents" / "pixel-spark-explorer.toml").read_text(encoding="utf-8")
        worker = (SKILL / "agents" / "pixel-spark-worker.toml").read_text(encoding="utf-8")
        reviewer = (SKILL / "agents" / "pixel-smart-reviewer.toml").read_text(encoding="utf-8")
        subagents = (SKILL / "references" / "subagents.md").read_text(encoding="utf-8")
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn('model = "gpt-5.3-codex-spark"', explorer)
        self.assertIn('sandbox_mode = "read-only"', explorer)
        self.assertIn('model = "gpt-5.3-codex-spark"', worker)
        self.assertIn('sandbox_mode = "workspace-write"', worker)
        self.assertIn('model = "gpt-5.5"', reviewer)
        self.assertIn("must not hand-edit `.pixel-goal/state.md`", subagents)
        self.assertIn("must attempt delegation", subagents)
        self.assertIn("Never change generated .pixel-goal artifacts", worker)
        self.assertIn("copying the TOML files into `.codex/agents/`", skill)
        self.assertIn("must attempt delegation", skill)
        self.assertNotIn("orchestrator", explorer.lower())
        self.assertNotIn("orchestrator", worker.lower())
        self.assertNotIn("orchestrator", subagents.lower())


if __name__ == "__main__":
    unittest.main()
