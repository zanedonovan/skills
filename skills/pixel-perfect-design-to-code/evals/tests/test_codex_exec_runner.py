from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from eval_suite import PIXEL_EVALS, load_pixel_eval_module


run_codex_exec = load_pixel_eval_module("run_codex_exec")
CodexExecConfig = run_codex_exec.CodexExecConfig
build_codex_exec_command = run_codex_exec.build_codex_exec_command
codex_exec_main = run_codex_exec.main
run_case = run_codex_exec.run_case
_manifest_matches = run_codex_exec._manifest_matches
_baseline_prompt = run_codex_exec._baseline_prompt
_review_artifact_fingerprint = run_codex_exec._review_artifact_fingerprint
_live_prompt = run_codex_exec._live_prompt
_select_cases = run_codex_exec._select_cases

from mobile_grid_overlay.evals import (
    load_cases_json,
    public_actual_path,
    public_clean_actual_path,
    public_clean_mock_path,
    public_mock_path,
)

ROOT = Path(__file__).resolve().parents[4]


class CodexExecRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = load_cases_json(PIXEL_EVALS / "cases.json")[0]

    def _write_fake_codex(self, tmp_path: Path, output_payload: str, return_code: int = 0, stdout_text: str = "") -> Path:
        fake_codex = tmp_path / "fake-codex"
        fake_codex.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import pathlib",
                    "import sys",
                    "",
                    "out = ''",
                    "args = sys.argv[1:]",
                    "for i, arg in enumerate(args):",
                    "    if arg == '--output-last-message' and i + 1 < len(args):",
                    "        out = args[i + 1]",
                    "        break",
                    "if out:",
                    f"    pathlib.Path(out).write_text({output_payload!r}, encoding='utf-8')",
                    f"sys.stdout.write({stdout_text!r})",
                    f"sys.exit({return_code})",
                ]
            ),
            encoding="utf-8",
        )
        fake_codex.chmod(0o755)
        return fake_codex

    def test_builds_codex_exec_command_with_images_and_output_capture(self) -> None:
        config = CodexExecConfig(
            codex_bin="codex",
            model="gpt-test",
            sandbox="read-only",
            cwd=ROOT,
            attach_images=True,
        )

        command = build_codex_exec_command(self.case, config, Path("last.txt"))

        self.assertEqual("codex", command[0])
        self.assertIn("exec", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--ephemeral", command)
        self.assertNotIn("--ask-for-approval", command)
        self.assertIn("--output-last-message", command)
        self.assertIn("last.txt", command)
        self.assertIn("--json", command)
        self.assertIn("--model", command)
        self.assertIn("gpt-test", command)
        self.assertIn(str(PIXEL_EVALS / public_clean_mock_path(self.case)), command)
        self.assertIn(str(PIXEL_EVALS / public_clean_actual_path(self.case)), command)
        self.assertIn(str(PIXEL_EVALS / public_mock_path(self.case)), command)
        self.assertIn(str(PIXEL_EVALS / public_actual_path(self.case)), command)
        self.assertEqual("-", command[-1])

    def test_runner_requires_explicit_case_or_all(self) -> None:
        with self.assertRaises(SystemExit):
            codex_exec_main(["--dry-run"])

    def test_runner_writes_json_from_fake_codex_exec(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_codex = tmp_path / "fake-codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "out=''",
                        "while [ $# -gt 0 ]; do",
                        "  if [ \"$1\" = '--output-last-message' ]; then",
                        "    shift",
                        "    out=\"$1\"",
                        "  fi",
                        "  shift",
                        "done",
                        "cat >/dev/null",
                        "printf '%s\\n' '{\"findings\":[{\"severity\":\"medium\",\"cells\":[\"A1\",\"B1\"],\"mask_id\":\"M1\",\"point\":[116,82],\"component\":\"header title\",\"difference\":\"shifted down\",\"evidence\":\"about 8 px too low\"}],\"summary\":\"Header differs.\"}' > \"$out\"",
                        "printf '%s\\n' 'fake codex stdout'",
                    ]
                ),
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            out_json = tmp_path / "answers.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = codex_exec_main(
                    [
                        "--case-id",
                        "ios_header_shift",
                        "--codex-bin",
                        str(fake_codex),
                        "--out",
                        str(out_json),
                        "--no-images",
                    ]
                )

            self.assertEqual(0, exit_code)
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            row = payload["answers"][0]
            self.assertEqual("ios_header_shift", row["id"])
            self.assertIn("run_id", payload)
            self.assertIn("run_metadata", payload)
            self.assertEqual(payload["run_id"], payload["run_metadata"]["run_id"])
            self.assertEqual("pixel-perfect-design-to-code", payload["run_metadata"]["target_skill"]["name"])
            self.assertIn("answer", row)
            self.assertIn("run", row)
            self.assertIn("run_id", row["run"])
            self.assertNotIn("with_skill", row)
            self.assertNotIn("with_skill_run", row)
            self.assertIn("point", row["answer"]["findings"][0])
            self.assertIn("Answers:", stdout.getvalue())

    def test_runner_supports_compare_baseline_and_writes_both_runs(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_codex = tmp_path / "fake-codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "out=''",
                        "while [ $# -gt 0 ]; do",
                        "  if [ \"$1\" = '--output-last-message' ]; then",
                        "    shift",
                        "    out=\"$1\"",
                        "  fi",
                        "  shift",
                        "done",
                        "cat >/dev/null",
                        "printf '%s\\n' '{\"findings\":[{\"severity\":\"low\",\"cells\":[\"A1\",\"B1\"],\"mask_id\":\"M1\",\"point\":[116,82],\"component\":\"header title\",\"difference\":\"shifted down\",\"evidence\":\"about 8 px too low\"}],\"summary\":\"Header differs.\"}' > \"$out\"",
                        "printf '%s\\n' 'fake codex stdout'",
                    ]
                ),
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            out_json = tmp_path / "answers.json"
            transcripts_dir = tmp_path / "transcripts"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = codex_exec_main(
                    [
                        "--case-id",
                        "ios_header_shift",
                        "--codex-bin",
                        str(fake_codex),
                        "--out",
                        str(out_json),
                        "--transcripts-dir",
                        str(transcripts_dir),
                        "--compare-baseline",
                        "--no-images",
                    ]
                )

            self.assertEqual(0, exit_code)
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            answer_rows = payload["answers"]
            self.assertEqual(1, len(answer_rows))
            row = answer_rows[0]
            self.assertIn("with_skill", row)
            self.assertIn("without_skill", row)
            self.assertIn("with_skill_run", row)
            self.assertIn("without_skill_run", row)
            self.assertIsInstance(row["with_skill_run"], dict)
            self.assertIsInstance(row["without_skill_run"], dict)
            self.assertIn("duration_ms", row["with_skill_run"])
            self.assertIn("duration_ms", row["without_skill_run"])
            self.assertTrue((transcripts_dir / "ios_header_shift_with_skill_last_message.json").exists())
            self.assertTrue((transcripts_dir / "ios_header_shift_without_skill_last_message.json").exists())
            with_transcript = json.loads(
                (transcripts_dir / "ios_header_shift_with_skill_last_message.json").read_text(
                    encoding="utf-8"
                )
            )
            without_transcript = json.loads(
                (transcripts_dir / "ios_header_shift_without_skill_last_message.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("Use the $pixel-perfect-design-to-code skill", with_transcript["prompt"])
            self.assertEqual(payload["run_id"], with_transcript["run_id"])
            with_cd = with_transcript["command"][with_transcript["command"].index("--cd") + 1]
            self.assertNotEqual(str(ROOT), with_cd)
            self.assertIn("Do not use any Codex skills", without_transcript["prompt"])
            self.assertIn("--ignore-user-config", without_transcript["command"])
            self.assertIn("--ignore-rules", without_transcript["command"])
            baseline_cd = without_transcript["command"][without_transcript["command"].index("--cd") + 1]
            self.assertNotEqual(str(ROOT), baseline_cd)
            self.assertIn("WROTE ios_header_shift", stdout.getvalue())

    def test_run_case_records_json_trace_and_flags_tool_calls(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_codex = self._write_fake_codex(
                tmp_path,
                output_payload='{"findings":[{"severity":"medium","cells":["A1","B1"],"mask_id":"M1","point":[116,82],"component":"header title","difference":"shifted down","evidence":"about 8 px too low"}],"summary":"Header differs."}',
                stdout_text=(
                    '{"type":"skill_activation","name":"pixel-perfect-design-to-code"}\n'
                    '{"type":"tool_call","name":"exec_command",'
                    '"arguments":{"cmd":"cat skills/pixel-perfect-design-to-code/evals/cases.json"}}\n'
                ),
            )
            out_json = tmp_path / "transcript.json"
            config = CodexExecConfig(
                codex_bin=str(fake_codex),
                model=None,
                sandbox="read-only",
                cwd=ROOT,
                attach_images=False,
            )

            answer, meta = run_case(self.case, "prompt", config, out_json)
            transcript = json.loads(out_json.read_text(encoding="utf-8"))

            self.assertEqual("Header differs.", answer["summary"])
            self.assertEqual(2, meta["json_event_count"])
            self.assertEqual(1, meta["tool_call_count"])
            self.assertIn("tool calls are forbidden", meta["trace_errors"][0])
            self.assertTrue(any("eval artifact access" in error for error in meta["trace_errors"]))
            self.assertEqual(meta["trace_errors"], transcript["trace_errors"])

    def test_compare_dry_run_does_not_leak_with_skill_args_into_baseline(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            out_json = tmp_path / "answers.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = codex_exec_main(
                    [
                        "--case-id",
                        "ios_header_shift",
                        "--out",
                        str(out_json),
                        "--dry-run",
                        "--compare-baseline",
                        "--no-images",
                        "--with-skill-extra-args",
                        "WITH_SKILL_ARG",
                        "--without-skill-extra-args",
                        "WITHOUT_SKILL_ARG",
                    ]
                )

            self.assertEqual(0, exit_code)
            lines = [line for line in stdout.getvalue().splitlines() if line.startswith("codex exec")]
            self.assertEqual(2, len(lines))
            self.assertIn("WITH_SKILL_ARG", lines[0])
            self.assertNotIn("WITHOUT_SKILL_ARG", lines[0])
            self.assertIn("WITHOUT_SKILL_ARG", lines[1])
            self.assertNotIn("WITH_SKILL_ARG", lines[1])
            self.assertIn("--ignore-user-config", lines[1])
            self.assertIn("--ignore-rules", lines[1])

    def test_compare_uses_clean_first_plus_review_artifacts_only_for_skill_run(self) -> None:
        config = CodexExecConfig(
            codex_bin="codex",
            model=None,
            sandbox="read-only",
            cwd=ROOT,
            attach_images=True,
        )

        with_command = build_codex_exec_command(
            self.case,
            config,
            Path("with.txt"),
            run_mode="with_skill",
        )
        without_command = build_codex_exec_command(
            self.case,
            config,
            Path("without.txt"),
            run_mode="without_skill",
        )

        self.assertIn(str(PIXEL_EVALS / public_clean_mock_path(self.case)), with_command)
        self.assertIn(str(PIXEL_EVALS / public_clean_actual_path(self.case)), with_command)
        self.assertTrue(any("review_artifacts" in value for value in with_command))
        self.assertTrue(any("review_panel.png" in value for value in with_command))
        self.assertTrue(any("strict_diff.png" in value for value in with_command))
        self.assertTrue(any("structural_heatmap.png" in value for value in with_command))
        self.assertIn(str(PIXEL_EVALS / public_mock_path(self.case)), with_command)
        self.assertIn(str(PIXEL_EVALS / public_actual_path(self.case)), with_command)
        self.assertIn(str(PIXEL_EVALS / public_clean_mock_path(self.case)), without_command)
        self.assertIn(str(PIXEL_EVALS / public_clean_actual_path(self.case)), without_command)
        self.assertFalse(any("review_artifacts" in value for value in without_command))
        self.assertNotIn(str(PIXEL_EVALS / public_mock_path(self.case)), without_command)
        self.assertNotIn(str(PIXEL_EVALS / public_actual_path(self.case)), without_command)

    def test_full_baseline_mode_can_use_same_review_artifacts(self) -> None:
        config = CodexExecConfig(
            codex_bin="codex",
            model=None,
            sandbox="read-only",
            cwd=ROOT,
            attach_images=True,
        )

        command = build_codex_exec_command(
            self.case,
            config,
            Path("without.txt"),
            run_mode="without_skill_full",
        )

        self.assertIn(str(PIXEL_EVALS / public_clean_mock_path(self.case)), command)
        self.assertIn(str(PIXEL_EVALS / public_clean_actual_path(self.case)), command)
        self.assertTrue(any("review_artifacts" in value for value in command))
        self.assertIn(str(PIXEL_EVALS / public_mock_path(self.case)), command)
        self.assertIn(str(PIXEL_EVALS / public_actual_path(self.case)), command)

    def test_runner_supports_repeated_compare_attempts(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_codex = self._write_fake_codex(
                tmp_path,
                output_payload='{"findings":[{"severity":"medium","cells":["A1","B1"],"mask_id":"M1","point":[116,82],"component":"header title","difference":"shifted down","evidence":"about 8 px too low"}],"summary":"Header differs."}',
            )
            out_json = tmp_path / "answers.json"
            transcripts_dir = tmp_path / "transcripts"

            exit_code = codex_exec_main(
                [
                    "--case-id",
                    "ios_header_shift",
                    "--codex-bin",
                    str(fake_codex),
                    "--out",
                    str(out_json),
                    "--transcripts-dir",
                    str(transcripts_dir),
                    "--compare-baseline",
                    "--repeat",
                    "2",
                    "--no-images",
                ]
            )

            payload = json.loads(out_json.read_text(encoding="utf-8"))
            row = payload["answers"][0]
            self.assertEqual(0, exit_code)
            self.assertIn("run_id", payload)
            self.assertEqual(2, len(row["with_skill_attempts"]))
            self.assertEqual(2, len(row["without_skill_attempts"]))
            self.assertTrue(
                (transcripts_dir / "ios_header_shift_with_skill_attempt_1_last_message.json").exists()
            )
            self.assertTrue(
                (transcripts_dir / "ios_header_shift_without_skill_attempt_2_last_message.json").exists()
            )

    def test_review_artifact_manifest_uses_input_and_script_hashes(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "target.png"
            actual = tmp_path / "actual.png"
            script = tmp_path / "tool.py"
            manifest = tmp_path / "manifest.json"
            target.write_bytes(b"target")
            actual.write_bytes(b"actual")
            script.write_text("print('tool')", encoding="utf-8")
            fingerprint = _review_artifact_fingerprint(
                target=target,
                actual=actual,
                script=script,
                ignore_rects=("0,0,10,10",),
            )
            manifest.write_text(json.dumps(fingerprint), encoding="utf-8")

            self.assertTrue(_manifest_matches(manifest, fingerprint))
            script.write_text("print('changed')", encoding="utf-8")
            changed = _review_artifact_fingerprint(
                target=target,
                actual=actual,
                script=script,
                ignore_rects=("0,0,10,10",),
            )
            self.assertFalse(_manifest_matches(manifest, changed))

    def test_prompts_explicitly_select_skill_mode(self) -> None:
        self.assertIn(
            "Use the $pixel-perfect-design-to-code skill",
            _live_prompt("base prompt"),
        )
        self.assertIn(
            "Do not use any Codex skills",
            _baseline_prompt("base prompt"),
        )

    def test_select_cases_with_missing_case_id_should_fail(self) -> None:
        with self.assertRaises(SystemExit) as context:
            _select_cases([self.case], ["missing_case"], False)

        self.assertIn("case not found", str(context.exception))

    def test_select_cases_rejects_all_and_case_id(self) -> None:
        with self.assertRaises(SystemExit):
            _select_cases([self.case], ["ios_header_shift"], True)

    def test_build_command_excludes_images_when_images_disabled(self) -> None:
        config = CodexExecConfig(
            codex_bin="codex",
            model="gpt-test",
            sandbox="read-only",
            cwd=ROOT,
            attach_images=False,
        )

        command = build_codex_exec_command(self.case, config, Path("last.txt"))

        self.assertNotIn("--image", command)

    def test_run_case_uses_transcript_output_when_stdout_empty(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_codex = self._write_fake_codex(
                tmp_path,
                output_payload='{"findings":[{"severity":"medium","cells":["A1"],"mask_id":"M1","point":[10,10],"component":"header","difference":"shift","evidence":"shifted"},{"severity":"low","cells":["B1"],"mask_id":"none","point":[20,20],"component":"icon","difference":"wrong","evidence":"missing"}],"summary":"ok"}',
            )
            out_json = tmp_path / "transcript.json"
            config = CodexExecConfig(
                codex_bin=str(fake_codex),
                model=None,
                sandbox="read-only",
                cwd=ROOT,
                attach_images=False,
            )

            answer, meta = run_case(self.case, "prompt", config, out_json)

            self.assertEqual("ok", answer["summary"])
            self.assertIn("duration_ms", meta)
            self.assertIn("token_count", meta)
            self.assertTrue(out_json.exists())
            parsed = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual("single", parsed["run_mode"])

    def test_run_case_fallback_to_stdout_if_no_transcript_output(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_codex = self._write_fake_codex(
                tmp_path,
                output_payload="",
                return_code=0,
                stdout_text='{"findings":[{"severity":"medium","cells":["C1"],"mask_id":"M2","point":[30,30],"component":"text","difference":"offset","evidence":"shifted"}],"summary":"stdout-only"}',
            )
            out_json = tmp_path / "transcript.json"
            config = CodexExecConfig(
                codex_bin=str(fake_codex),
                model=None,
                sandbox="read-only",
                cwd=ROOT,
                attach_images=False,
            )

            answer, _ = run_case(self.case, "prompt", config, out_json)

            self.assertEqual("stdout-only", answer["summary"])

    def test_run_case_raises_and_records_error_on_failed_execution(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fake_codex = self._write_fake_codex(
                tmp_path,
                output_payload="",
                return_code=7,
                stdout_text="boom",
            )
            out_json = tmp_path / "transcript.json"
            config = CodexExecConfig(
                codex_bin=str(fake_codex),
                model=None,
                sandbox="read-only",
                cwd=ROOT,
                attach_images=False,
            )

            with self.assertRaises(RuntimeError):
                run_case(self.case, "prompt", config, out_json)

            transcript = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(self.case.id, transcript["case_id"])
            self.assertEqual(7, transcript["return_code"])
            self.assertIn("boom", transcript["stderr"] + transcript["stdout"])

    def test_dry_run_does_not_write_answers_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            out_json = tmp_path / "answers.json"
            original = {"answers": [{"id": "ios_header_shift", "answer": {"summary": "existing"}}]}
            out_json.write_text(json.dumps(original, indent=2, ensure_ascii=False), encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = codex_exec_main(
                    [
                        "--case-id",
                        "ios_header_shift",
                        "--out",
                        str(out_json),
                        "--dry-run",
                        "--no-images",
                    ]
                )

            self.assertEqual(0, exit_code)
            after = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(original, after)
            self.assertIn("===== ios_header_shift =====", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
