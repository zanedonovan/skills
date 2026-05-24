"""Preset runner for the skill eval workflow."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]
EVALS_ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run common eval workflow presets.")
    parser.add_argument(
        "preset",
        choices=(
            "quick",
            "integration",
            "report",
            "live-smoke",
            "live-artifact-smoke",
            "live-benchmark",
            "live-artifact-benchmark",
        ),
        help="Workflow preset to run.",
    )
    parser.add_argument("--case-id", default="ios_header_shift")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out-dir", default=str(EVALS_ROOT))
    parser.add_argument("--run-id", help="Stable id for live workflow artifacts.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")

    run_id = args.run_id or new_run_id("workflow")
    commands = build_workflow_commands(
        args.preset,
        case_id=args.case_id,
        repeat=args.repeat,
        out_dir=Path(args.out_dir),
        run_id=run_id,
    )
    for command in commands:
        if args.dry_run:
            print(" ".join(command))
            continue
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


def build_workflow_commands(
    preset: str,
    *,
    case_id: str,
    repeat: int,
    out_dir: Path,
    run_id: str = "workflow-manual",
) -> tuple[list[str], ...]:
    python = sys.executable
    if preset == "quick":
        return ([python, "-m", "pytest", str(EVALS_ROOT / "tests"), "-m", "eval and fast"],)
    if preset == "integration":
        return ([python, "-m", "pytest", str(EVALS_ROOT / "tests"), "-m", "eval and integration"],)
    if preset == "report":
        return ([python, str(EVALS_ROOT / "generate_side_by_side.py")],)
    if preset in {
        "live-smoke",
        "live-artifact-smoke",
        "live-benchmark",
        "live-artifact-benchmark",
    }:
        all_cases = preset in {"live-benchmark", "live-artifact-benchmark"}
        out_dir = out_dir.resolve()
        run_dir = out_dir / "runs" / run_id
        answers = run_dir / "answers.json"
        grading = run_dir / "grading.json"
        benchmark = run_dir / "benchmark.json"
        transcripts = run_dir / "transcripts"
        report = run_dir / "side_by_side.html"
        codex_command = [
            python,
            str(EVALS_ROOT / "run_codex_exec.py"),
            "--run-id",
            run_id,
            "--out",
            str(answers),
            "--compare-baseline",
            "--repeat",
            str(repeat),
            "--transcripts-dir",
            str(transcripts),
        ]
        if all_cases:
            codex_command.append("--all")
        else:
            codex_command.extend(["--case-id", case_id])
        if preset in {"live-artifact-smoke", "live-artifact-benchmark"}:
            codex_command.extend(["--without-skill-images", "full"])
        grade_command = [
            python,
            str(EVALS_ROOT / "run_evals.py"),
            "--compare",
            "--answers",
            str(answers),
            "--run-id",
            run_id,
            "--grading-out",
            str(grading),
            "--benchmark-out",
            str(benchmark),
        ]
        if all_cases:
            grade_command.append("--production-gate")
        report_command = [
            python,
            str(EVALS_ROOT / "generate_side_by_side.py"),
            "--answers",
            str(answers),
            "--transcripts-dir",
            str(transcripts),
            "--out",
            str(report),
        ]
        if not all_cases:
            grade_command.extend(["--case-id", case_id])
            report_command.extend(["--case-id", case_id])
        return (codex_command, grade_command, report_command)
    raise ValueError(f"unknown preset: {preset}")


def new_run_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid4().hex[:8]}"


if __name__ == "__main__":
    raise SystemExit(main())
