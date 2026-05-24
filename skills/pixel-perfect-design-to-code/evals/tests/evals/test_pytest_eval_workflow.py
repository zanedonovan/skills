from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_suite import PIXEL_EVALS, load_pixel_eval_module


codex_exec_main = load_pixel_eval_module("run_codex_exec").main
run_evals_main = load_pixel_eval_module("run_evals").main


ROOT = Path(__file__).resolve().parents[5]


@pytest.mark.eval
@pytest.mark.fast
def test_sample_answers_pass_under_pytest(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = run_evals_main(["--answers", str(PIXEL_EVALS / "sample_answers.json")])

    assert exit_code == 0
    assert "Score: 15/15 cases passed" in capsys.readouterr().out


@pytest.mark.eval
@pytest.mark.fast
def test_adversarial_answers_fail_under_pytest(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = run_evals_main(["--answers", str(PIXEL_EVALS / "adversarial_answers.json")])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL ios_header_shift" in output
    assert "FAIL ios_cta_geometry_stack" in output
    assert "Score: 0/15 cases passed" in output


@pytest.mark.eval
@pytest.mark.fast
@pytest.mark.parametrize(
    "case_id",
    [
        "ios_card_radius_too_round",
        "android_card_radius_too_square",
        "ios_cta_radius_too_square",
    ],
)
def test_rounded_corner_hard_negatives_fail_under_pytest(case_id: str) -> None:
    exit_code = run_evals_main(
        [
            "--answers",
            str(PIXEL_EVALS / "rounded_corner_fail_answers.json"),
            "--case-id",
            case_id,
        ]
    )

    assert exit_code == 1


@pytest.mark.eval
@pytest.mark.fast
def test_compare_mode_requires_without_skill_answer(tmp_path: Path) -> None:
    answers_path = tmp_path / "answers.json"
    answers_path.write_text(
        json.dumps(
            {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "with_skill": {
                            "findings": [
                                {
                                    "severity": "medium",
                                    "cells": ["A1", "B1"],
                                    "mask_id": "M1",
                                    "point": [116, 82],
                                    "component": "header title",
                                    "difference": "shifted down",
                                    "evidence": "about 8 px too low",
                                }
                            ],
                            "summary": "Header differs.",
                        },
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="missing without_skill answer"):
        run_evals_main(
            [
                "--answers",
                str(answers_path),
                "--compare",
                "--case-id",
                "ios_header_shift",
            ]
        )


@pytest.mark.eval
@pytest.mark.integration
def test_compare_mode_writes_grading_and_benchmark_artifacts(tmp_path: Path) -> None:
    answers_path = tmp_path / "answers.json"
    grading_path = tmp_path / "grading.json"
    benchmark_path = tmp_path / "benchmark.json"
    answers_path.write_text(
        json.dumps(
            {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "with_skill": {
                            "findings": [
                                {
                                    "severity": "medium",
                                    "cells": ["A1", "B1"],
                                    "mask_id": "M1",
                                    "point": [116, 82],
                                    "component": "header title",
                                    "difference": "shifted down",
                                    "evidence": "about 8 px too low",
                                }
                            ],
                            "summary": "Header differs.",
                        },
                        "with_skill_run": {"duration_ms": 300.0, "token_count": 200},
                        "without_skill": {"findings": [], "summary": "No visible differences."},
                        "without_skill_run": {"duration_ms": 120.0, "token_count": 80},
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    exit_code = run_evals_main(
        [
            "--answers",
            str(answers_path),
            "--compare",
            "--case-id",
            "ios_header_shift",
            "--grading-out",
            str(grading_path),
            "--benchmark-out",
            str(benchmark_path),
        ]
    )

    grading = json.loads(grading_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert grading["comparisons"][0]["label"] == "improved"
    assert benchmark["patterns"]["improved"] == ["ios_header_shift"]


@pytest.mark.eval
@pytest.mark.live
def test_live_codex_exec_case_can_be_graded(tmp_path: Path) -> None:
    answers_path = tmp_path / "codex_exec_answers.json"
    grading_path = tmp_path / "grading.json"
    benchmark_path = tmp_path / "benchmark.json"

    exec_code = codex_exec_main(
        [
            "--case-id",
            "ios_header_shift",
            "--out",
            str(answers_path),
            "--compare-baseline",
            "--transcripts-dir",
            str(tmp_path / "transcripts"),
        ]
    )
    grade_code = run_evals_main(
        [
            "--answers",
            str(answers_path),
            "--compare",
            "--case-id",
            "ios_header_shift",
            "--grading-out",
            str(grading_path),
            "--benchmark-out",
            str(benchmark_path),
        ]
    )

    assert exec_code == 0
    assert grade_code == 0
    assert grading_path.is_file()
    assert benchmark_path.is_file()
