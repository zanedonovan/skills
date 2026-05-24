from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from eval_suite import PIXEL_EVALS, load_pixel_eval_module


workflow = load_pixel_eval_module("workflow")
ROOT = workflow.ROOT
build_workflow_commands = workflow.build_workflow_commands
workflow_main = workflow.main


class EvalWorkflowCliTests(unittest.TestCase):
    def test_quick_preset_hides_pytest_marker_flags(self) -> None:
        commands = build_workflow_commands(
            "quick",
            case_id="ios_header_shift",
            repeat=1,
            out_dir=PIXEL_EVALS,
            run_id="run-test",
        )

        self.assertEqual(([sys.executable, "-m", "pytest", str(PIXEL_EVALS / "tests"), "-m", "eval and fast"],), commands)

    def test_live_smoke_preset_builds_capture_grade_and_report_steps(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir)
            commands = build_workflow_commands(
                "live-smoke",
                case_id="ios_header_shift",
                repeat=2,
                out_dir=out_dir,
                run_id="run-test",
            )

        self.assertEqual(3, len(commands))
        self.assertIn("run_codex_exec.py", commands[0][1])
        self.assertIn("--run-id", commands[0])
        self.assertIn("run-test", commands[0])
        self.assertIn("--compare-baseline", commands[0])
        self.assertIn("--repeat", commands[0])
        self.assertIn("2", commands[0])
        self.assertTrue(any("runs/run-test/answers.json" in value for value in commands[0]))
        self.assertIn("run_evals.py", commands[1][1])
        self.assertIn("--run-id", commands[1])
        self.assertIn("--benchmark-out", commands[1])
        self.assertNotIn("--production-gate", commands[1])
        self.assertIn("generate_side_by_side.py", commands[2][1])
        self.assertIn("--transcripts-dir", commands[2])

    def test_live_artifact_smoke_uses_full_baseline_images(self) -> None:
        commands = build_workflow_commands(
            "live-artifact-smoke",
            case_id="ios_header_shift",
            repeat=1,
            out_dir=PIXEL_EVALS,
            run_id="run-test",
        )

        self.assertIn("--without-skill-images", commands[0])
        self.assertIn("full", commands[0])

    def test_live_benchmark_runs_all_cases_without_case_filter(self) -> None:
        commands = build_workflow_commands(
            "live-benchmark",
            case_id="ios_header_shift",
            repeat=3,
            out_dir=PIXEL_EVALS,
            run_id="run-test",
        )

        self.assertIn("--all", commands[0])
        self.assertIn("--repeat", commands[0])
        self.assertIn("3", commands[0])
        self.assertNotIn("--case-id", commands[0])
        self.assertNotIn("--case-id", commands[1])
        self.assertNotIn("--case-id", commands[2])
        self.assertIn("--production-gate", commands[1])

    def test_live_artifact_benchmark_uses_full_baseline_images(self) -> None:
        commands = build_workflow_commands(
            "live-artifact-benchmark",
            case_id="ios_header_shift",
            repeat=3,
            out_dir=PIXEL_EVALS,
            run_id="run-test",
        )

        self.assertIn("--all", commands[0])
        self.assertIn("--without-skill-images", commands[0])
        self.assertIn("full", commands[0])

    def test_dry_run_prints_commands_without_running_them(self) -> None:
        exit_code = workflow_main(["quick", "--dry-run"])

        self.assertEqual(0, exit_code)


if __name__ == "__main__":
    unittest.main()
