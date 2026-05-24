from __future__ import annotations

import json
import re
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from eval_suite import PIXEL_EVALS, load_pixel_eval_module
from mobile_grid_overlay.evals import build_prompt, grade_answer as grade_structured_answer, load_cases_json


run_evals_main = load_pixel_eval_module("run_evals").main


ROOT = Path(__file__).resolve().parents[4]


def grade_answer(case, answer):
    if isinstance(answer, str):
        answer = _structured_test_answer(answer)
    return grade_structured_answer(case, answer)


def _structured_test_answer(text: str) -> dict[str, object]:
    cells = tuple(dict.fromkeys(match.group(1).upper() for match in re.finditer(r"\b([A-Za-z]\d{1,2})\b", text)))
    point_match = re.search(r"\b(?:point|target)\s*[:=]?\s*\"?\(?\s*(\d+)\s*,\s*(\d+)", text, re.I)
    point = [int(point_match.group(1)), int(point_match.group(2))] if point_match else []
    return {
        "findings": [
            {
                "severity": "medium",
                "cells": list(cells),
                "mask_id": "none",
                "point": point,
                "component": "test component",
                "difference": text,
                "evidence": text,
            }
        ],
        "summary": "",
    }


class EvalGraderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = {case.id: case for case in load_cases_json(PIXEL_EVALS / "cases.json")}

    def test_grader_passes_expected_visual_finding(self) -> None:
        result = grade_answer(
            self.cases["ios_header_shift"],
            "In A1/B1 the header title is shifted down and too low by about 8 px; point: 116,82.",
        )
        self.assertTrue(result.passed)
        self.assertEqual(("header title y shift",), result.matched_findings)

    def test_grader_rejects_unstructured_text_without_json_fallback(self) -> None:
        result = grade_structured_answer(
            self.cases["ios_header_shift"],
            "In A1/B1 the header title is shifted down and too low by about 8 px; point: 116,82.",
        )

        self.assertFalse(result.passed)
        self.assertEqual(("header title y shift",), result.missed_findings)

    def test_grader_allows_match_except_summary_when_finding_is_explicit(self) -> None:
        result = grade_answer(
            self.cases["ios_header_shift"],
            (
                "<findings>- severity: medium; cells: A1,B1; mask_id: none; point: 58,78; "
                "component: Dashboard header title; difference: implementation title is positioned "
                "lower than the mock; evidence: text baseline is at y=82 in implementation vs y=74 "
                "in mock, about +8px vertical offset with matching x position, size, weight, and color."
                "</findings><summary>The implementation matches the mock except for the Dashboard "
                "title being shifted down by about 8px.</summary>"
            ),
        )

        self.assertTrue(result.passed)
        self.assertEqual(("header title y shift",), result.matched_findings)

    def test_grader_does_not_count_matching_color_as_color_mismatch_false_alarm(self) -> None:
        result = grade_answer(
            self.cases["ios_header_shift"],
            (
                "<findings>- severity: medium; cells: A1-B1; mask_id: none; point: 80,79; "
                "component: Dashboard header title; difference: implementation title is shifted "
                "downward; evidence: mock text baseline is at y=74 while implementation baseline "
                "is at y=82, a +8px vertical offset, with matching x position, font size, color, "
                "and surrounding header elements.</findings><summary>The only app-content mismatch "
                "is the Dashboard title sitting one 8px grid step too low in the header.</summary>"
            ),
        )

        self.assertTrue(result.passed)
        self.assertEqual((), result.false_alarms)

    def test_grader_still_penalizes_real_color_mismatch_false_alarm(self) -> None:
        result = grade_answer(
            self.cases["ios_header_shift"],
            (
                "In A1/B1 the header title is shifted downward by 8 px; point: 80,79. "
                "There is also a color mismatch in the header text."
            ),
        )

        self.assertFalse(result.passed)
        self.assertEqual(("header title y shift",), result.matched_findings)
        self.assertEqual(("color mismatch",), result.false_alarms)

    def test_grader_accepts_structured_json_answer(self) -> None:
        answer = json.dumps(
            {
                "findings": [
                    {
                        "severity": "medium",
                        "cells": ["A1", "B1"],
                        "mask_id": "none",
                        "point": [80, 79],
                        "component": "Dashboard header title",
                        "difference": "implementation title is shifted downward",
                        "evidence": "baseline moved from y=74 to y=82, a +8px vertical offset",
                    }
                ],
                "summary": "The only app-content mismatch is the Dashboard title position.",
            }
        )

        result = grade_structured_answer(self.cases["ios_header_shift"], answer)

        self.assertTrue(result.passed)
        self.assertEqual(("header title y shift",), result.matched_findings)

    def test_grader_fails_invalid_structured_json_schema(self) -> None:
        result = grade_structured_answer(
            self.cases["ios_header_shift"],
            {
                "findings": [
                    {
                        "severity": "medium",
                        "cells": ["A1", "B1"],
                        "point": [999, 999],
                        "component": "header title",
                        "difference": "shifted down",
                        "evidence": "about 8 px too low",
                    }
                ],
                "summary": "Header differs.",
            },
        )

        self.assertFalse(result.passed)
        self.assertEqual(0.0, result.score)
        self.assertIn("findings[0].mask_id is required", result.schema_errors)
        self.assertIn(
            "findings[0].point must be [x, y] inside the screenshot bounds",
            result.schema_errors,
        )

    def test_structured_summary_is_not_scored_as_a_false_alarm(self) -> None:
        answer = json.dumps(
            {
                "findings": [
                    {
                        "severity": "medium",
                        "cells": ["A1", "B1"],
                        "mask_id": "none",
                        "point": [80, 79],
                        "component": "Dashboard header title",
                        "difference": "implementation title is shifted downward",
                        "evidence": "baseline moved from y=74 to y=82, a +8px vertical offset",
                    }
                ],
                "summary": "There is no color mismatch; only the title position changed.",
            }
        )

        result = grade_structured_answer(self.cases["ios_header_shift"], answer)

        self.assertTrue(result.passed)
        self.assertEqual((), result.false_alarms)

    def test_grader_accepts_point_inside_wide_button_box(self) -> None:
        result = grade_answer(
            self.cases["ios_button_color"],
            (
                "<findings>- severity: medium; cells: A7-D8; mask_id: none; point: 60,724; "
                "component: Continue button; difference: implementation button fill is purple "
                "instead of the mock iOS blue; evidence: same position and size, but color changed "
                "to #7c3aed in the implementation.</findings>"
            ),
        )

        self.assertTrue(result.passed)
        self.assertEqual(("primary button color",), result.matched_findings)

    def test_grader_accepts_point_inside_header_font_box(self) -> None:
        result = grade_answer(
            self.cases["android_shape_typography"],
            (
                "In A1/B1 the header title font is the wrong typeface and too small; point: 74,44. "
                "In C7/D7 the CTA label vertical center is too high by 4 px; point: 180,701. "
                "In C7/D7 the CTA corner radius is too round; point: 30,676."
            ),
        )

        self.assertTrue(result.passed)
        self.assertEqual(
            ("header title font mismatch", "button label vertical centering", "cta corner radius"),
            result.matched_findings,
        )

    def test_cases_can_define_per_finding_point_tolerance_and_boxes(self) -> None:
        findings = {
            finding.label: finding
            for finding in self.cases["ios_subtle_layout"].expected_findings
        }

        self.assertEqual((116, 77), findings["header title baseline"].target_point)
        self.assertEqual((58, 72, 174, 82), findings["header title baseline"].target_box)
        self.assertEqual(0, findings["header title baseline"].point_tolerance)
        self.assertEqual(10, findings["card corner radius"].point_tolerance)

    def test_rounded_corner_cases_are_present(self) -> None:
        self.assertIn("ios_card_radius_too_round", self.cases)
        self.assertIn("android_card_radius_too_square", self.cases)
        self.assertIn("ios_cta_radius_too_square", self.cases)

    def test_rounded_corner_case_passes_only_with_radius_evidence_and_point(self) -> None:
        result = grade_answer(
            self.cases["ios_card_radius_too_round"],
            (
                "In A2/B2 the top card corner radius is too round and too large "
                "compared with the mock; point: 28,142."
            ),
        )

        self.assertTrue(result.passed)
        self.assertEqual(("card corner radius too round",), result.matched_findings)

    def test_rounded_corner_case_fails_when_answer_only_mentions_shape_generically(self) -> None:
        result = grade_answer(
            self.cases["ios_cta_radius_too_square"],
            "In C7/D7 the CTA shape looks different, but I cannot localize the corner.",
        )

        self.assertFalse(result.passed)
        self.assertEqual(("cta corner radius too square",), result.missed_findings)

    def test_grader_fails_when_agent_point_is_far_from_expected_target(self) -> None:
        result = grade_answer(
            self.cases["ios_header_shift"],
            "In A1/B1 the header title is shifted down and too low by about 8 px; point: 320,420.",
        )

        self.assertFalse(result.passed)
        self.assertEqual(("header title y shift",), result.missed_findings)

    def test_subtle_finding_uses_stricter_point_tolerance(self) -> None:
        result = grade_answer(
            self.cases["ios_subtle_layout"],
            (
                "In A1/B1 the header title baseline is shifted down by about 3 px; point: 116,91. "
                "In B7/C7/D7 the CTA label vertical center is off and text is too low by 4 px; point: 195,738. "
                "In A2/B2 the card corner radius is too small and sharp / square; point: 28,142."
            ),
        )

        self.assertFalse(result.passed)
        self.assertEqual(0.667, result.score)
        self.assertEqual(
            ("button label vertical centering", "card corner radius"),
            result.matched_findings,
        )
        self.assertEqual(("header title baseline",), result.missed_findings)

    def test_large_finding_keeps_looser_point_tolerance(self) -> None:
        result = grade_answer(
            self.cases["android_missing_icon"],
            "In C1/D1 the search icon is missing; point: 346,44.",
        )

        self.assertTrue(result.passed)
        self.assertEqual(("search icon missing",), result.matched_findings)

    def test_grader_fails_when_region_is_missing(self) -> None:
        result = grade_answer(
            self.cases["android_missing_icon"],
            "The search icon is missing, but I cannot localize it.",
        )
        self.assertFalse(result.passed)
        self.assertEqual(("search icon missing",), result.missed_findings)

    def test_grader_penalizes_false_alarm_terms(self) -> None:
        result = grade_answer(
            self.cases["ios_button_color"],
            "In B6 the button has the wrong purple color, and the button is missing.",
        )
        self.assertFalse(result.passed)
        self.assertEqual(("missing button",), result.false_alarms)

    def test_grader_fails_when_answer_denies_the_mismatch(self) -> None:
        result = grade_answer(
            self.cases["ios_button_color"],
            "In B6/C6 the primary button color is correct and it is not purple.",
        )

        self.assertFalse(result.passed)
        self.assertEqual(("primary button color",), result.missed_findings)

    def test_multi_difference_case_requires_all_findings(self) -> None:
        case = self.cases["ios_subtle_layout"]
        result = grade_answer(
            case,
            "In A1/B1 the header title baseline is shifted down by about 3 px; point: 116,77.",
        )

        self.assertFalse(result.passed)
        self.assertEqual(0.333, result.score)
        self.assertEqual(("header title baseline",), result.matched_findings)
        self.assertEqual(
            ("button label vertical centering", "card corner radius"),
            result.missed_findings,
        )

    def test_multi_difference_case_passes_when_all_findings_are_present(self) -> None:
        case = self.cases["android_shape_typography"]
        result = grade_answer(
            case,
            (
                "In A1/B1 the header title has the wrong font and looks too small; point: 88,52. "
                "In C7/D7 the CTA label vertical center is off and too high by 4 px; point: 180,701. "
                "In C7/D7 the CTA corner radius is too round; point: 30,676."
            ),
        )

        self.assertTrue(result.passed)
        self.assertEqual(
            ("header title font mismatch", "button label vertical centering", "cta corner radius"),
            result.matched_findings,
        )

    def test_grader_rejects_cross_wired_multi_finding_answer(self) -> None:
        result = grade_structured_answer(
            self.cases["ios_dual_radius_color"],
            {
                "findings": [
                    {
                        "severity": "medium",
                        "cells": ["A2"],
                        "mask_id": "M1",
                        "point": [28, 142],
                        "component": "top card",
                        "difference": "wrong color purple hue",
                        "evidence": "wrong color purple hue",
                    },
                    {
                        "severity": "medium",
                        "cells": ["A7"],
                        "mask_id": "M2",
                        "point": [30, 708],
                        "component": "CTA corner",
                        "difference": "radius rounded too round too large",
                        "evidence": "radius rounded too round too large",
                    },
                    {
                        "severity": "medium",
                        "cells": ["B7"],
                        "mask_id": "M3",
                        "point": [195, 728],
                        "component": "CTA fill",
                        "difference": "radius sharp square too small",
                        "evidence": "radius sharp square too small",
                    },
                ],
                "summary": "Each individual finding is intentionally cross-wired.",
            },
        )

        self.assertFalse(result.passed)
        self.assertEqual(0.0, result.score)
        self.assertEqual(
            ("dual card radius too round", "dual cta radius too square", "dual cta color"),
            result.missed_findings,
        )

    def test_prompt_does_not_leak_case_notes_or_expected_answer(self) -> None:
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )
        prompt = build_prompt(self.cases["ios_header_shift"], template)

        self.assertNotIn("Notes:", prompt)
        self.assertNotIn("Title baseline is lower", prompt)

    def test_prompt_hides_case_identity(self) -> None:
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )
        prompt = build_prompt(self.cases["android_missing_icon"], template)

        self.assertNotIn("Case:", prompt)
        self.assertNotIn("case-", prompt)
        self.assertNotIn("evals/", prompt)
        self.assertNotIn("android_missing_icon", prompt)
        self.assertNotIn("missing_icon", prompt)
        self.assertNotIn("eval", prompt.casefold())
        self.assertNotIn("test", prompt.casefold())
        self.assertNotIn("model", prompt.casefold())

    def test_all_prompts_hide_internal_case_metadata(self) -> None:
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )

        for case in self.cases.values():
            with self.subTest(case=case.id):
                prompt = build_prompt(case, template)
                self.assertNotIn(case.id, prompt)
                self.assertNotIn(case.notes, prompt)
                self.assertNotIn(Path(case.mock_path).name, prompt)
                self.assertNotIn(Path(case.actual_path).name, prompt)

    def test_runner_prints_self_contained_inline_prompt(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = run_evals_main(["--print-prompts", "--case-id", "ios_header_shift"])

        output = stdout.getvalue()
        self.assertEqual(0, exit_code)
        self.assertIn("===== ios_header_shift =====", output)
        self.assertIn("You are reviewing two mobile app screenshots for visual parity", output)
        self.assertIn("Reference: first attached image, unannotated", output)
        self.assertIn("Implementation: second attached image, unannotated", output)
        self.assertIn("Optional review aids", output)
        self.assertIn("when grid images are available, name the macro cell", output)
        self.assertIn("Return only valid JSON", output)
        self.assertIn('"findings"', output)

    def test_prompt_allows_mask_ids_when_review_layers_are_visible(self) -> None:
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )
        prompt = build_prompt(self.cases["ios_header_shift"], template)

        self.assertIn("mask_id", prompt)
        self.assertIn("M1", prompt)

    def test_runner_returns_zero_when_all_sample_answers_pass(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = run_evals_main(["--answers", str(PIXEL_EVALS / "sample_answers.json")])

        self.assertEqual(0, exit_code)
        self.assertIn("Score: 15/15 cases passed", stdout.getvalue())

    def test_runner_returns_nonzero_when_any_answer_fails(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            answers_path = Path(tmp_dir) / "answers.json"
            answers = {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "answer": _structured_test_answer(
                            "The header title is shifted down, but I cannot localize it."
                        ),
                    },
                    {
                        "id": "android_cta_spacing",
                        "answer": _structured_test_answer(
                            "In C7 D7 the bottom CTA is too high by about 16 px; point: 180,682."
                        ),
                    },
                    {
                        "id": "ios_button_color",
                        "answer": _structured_test_answer(
                            "In B6 C6 the primary button is purple / wrong color; point: 195,728."
                        ),
                    },
                    {
                        "id": "android_missing_icon",
                        "answer": _structured_test_answer(
                            "In C1 D1 the search icon is missing; point: 322,44."
                        ),
                    },
                    {
                        "id": "ios_subtle_layout",
                        "answer": _structured_test_answer(
                            "In A1 B1 the header title baseline is too low by 3 px; point: 116,77. "
                            "In B7 C7 the CTA label vertical center is off and too low by 4 px; point: 195,738. "
                            "In A2 B2 the card corner radius is too small / square; point: 28,142."
                        ),
                    },
                    {
                        "id": "android_shape_typography",
                        "answer": _structured_test_answer(
                            "In A1 B1 the header title font is too small / wrong font; point: 88,52. "
                            "In C7 D7 the CTA label vertical center is too high by 4 px; point: 180,701. "
                            "In C7 D7 the CTA corner radius is too round; point: 30,676."
                        ),
                    },
                    {
                        "id": "ios_card_radius_too_round",
                        "answer": _structured_test_answer(
                            "In A2 B2 the top card corner radius is too round / too large; point: 28,142."
                        ),
                    },
                    {
                        "id": "android_card_radius_too_square",
                        "answer": _structured_test_answer(
                            "In A2 B2 the card corner radius is too small / square / sharp; point: 28,118."
                        ),
                    },
                    {
                        "id": "ios_cta_radius_too_square",
                        "answer": _structured_test_answer(
                            "In B7 C7 D7 the CTA corner radius is too small / square / sharp; point: 30,708."
                        ),
                    },
                    {
                        "id": "ios_compound_header_cta",
                        "answer": _structured_test_answer(
                            "In A1 B1 the header title is shifted down / too low by 6 px; point: 116,80. "
                            "In C1 D1 the search icon is missing / absent; point: 352,66. "
                            "In B7 C7 D7 the Continue CTA button has wrong color / purple / not blue; point: 195,728. "
                            "In B7 C7 D7 the CTA label vertical center is off and too low by 4 px; point: 195,738."
                        ),
                    },
                    {
                        "id": "android_micro_shape_text",
                        "answer": _structured_test_answer(
                            "In A1 B1 the header title font is wrong typeface / wrong size / too small; point: 88,52. "
                            "In A2 B2 the card corner radius is too small / square / sharp; point: 28,118. "
                            "In C7 D7 the CTA label vertical center is off and too high by 4 px; point: 180,701."
                        ),
                    },
                    {
                        "id": "ios_dual_radius_color",
                        "answer": _structured_test_answer(
                            "In A2 B2 the top card corner radius is too round / too large; point: 28,142. "
                            "In B7 C7 D7 the CTA corner radius is too small / square / sharp; point: 30,708. "
                            "In B7 C7 D7 the Continue CTA button has wrong color / purple / not blue; point: 195,728."
                        ),
                    },
                    {
                        "id": "ios_precision_stack",
                        "answer": _structured_test_answer(
                            "In A1 B1 the header title is shifted down / too low by 2 px; point: 116,76. "
                            "In C1 D1 the search icon is shifted left by 7 px; point: 345,66. "
                            "In A2 B2 C2 D2 the card is shifted right and narrower by 8 px; point: 196,215. "
                            "In B7 C7 D7 the CTA label vertical center is off and too low by 3 px; point: 195,738."
                        ),
                    },
                    {
                        "id": "android_conflicting_shapes",
                        "answer": _structured_test_answer(
                            "In A1 B1 the header title font is wrong typeface / wrong size / too small; point: 88,52. "
                            "In A2 B2 the card corner radius is too round / too large; point: 28,118. "
                            "In B7 C7 D7 the CTA corner radius is too small / square / sharp; point: 30,676. "
                            "In B7 C7 D7 the CTA button color is wrong shade / darker blue / wrong hue; point: 180,698."
                        ),
                    },
                    {
                        "id": "ios_cta_geometry_stack",
                        "answer": _structured_test_answer(
                            "In A7 B7 C7 D7 the CTA is shifted up / too high by 7 px, narrower by 10 px and shorter / compressed; point: 195,719. "
                            "In A7 B7 C7 D7 the CTA corner radius is too small / square / sharp; point: 35,701. "
                            "In B7 C7 D7 the CTA label vertical center is off and too high by 3 px; point: 195,725."
                        ),
                    },
                ]
            }
            answers_path.write_text(
                json.dumps(answers, indent=2),
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = run_evals_main(["--answers", str(answers_path)])

        output = stdout.getvalue()
        self.assertEqual(1, exit_code)
        self.assertIn("FAIL ios_header_shift", output)
        self.assertIn("missed: header title y shift", output)
        self.assertIn("Score: 14/15 cases passed", output)

    def test_adversarial_answers_fail_all_cases(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = run_evals_main(
                ["--answers", str(PIXEL_EVALS / "adversarial_answers.json")]
            )

        output = stdout.getvalue()
        self.assertEqual(1, exit_code)
        self.assertIn("FAIL ios_header_shift", output)
        self.assertIn("FAIL android_cta_spacing", output)
        self.assertIn("FAIL ios_button_color", output)
        self.assertIn("FAIL android_missing_icon", output)
        self.assertIn("FAIL ios_subtle_layout", output)
        self.assertIn("FAIL android_shape_typography", output)
        self.assertIn("FAIL ios_card_radius_too_round", output)
        self.assertIn("FAIL android_card_radius_too_square", output)
        self.assertIn("FAIL ios_cta_radius_too_square", output)
        self.assertIn("FAIL ios_compound_header_cta", output)
        self.assertIn("FAIL android_micro_shape_text", output)
        self.assertIn("FAIL ios_dual_radius_color", output)
        self.assertIn("FAIL ios_precision_stack", output)
        self.assertIn("FAIL android_conflicting_shapes", output)
        self.assertIn("FAIL ios_cta_geometry_stack", output)
        self.assertIn("Score: 0/15 cases passed", output)

    def test_rounded_corner_fail_answers_fail_new_cases(self) -> None:
        for case_id in (
            "ios_card_radius_too_round",
            "android_card_radius_too_square",
            "ios_cta_radius_too_square",
        ):
            with self.subTest(case=case_id):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = run_evals_main(
                        [
                            "--answers",
                            str(PIXEL_EVALS / "rounded_corner_fail_answers.json"),
                            "--case-id",
                            case_id,
                        ]
                    )

                self.assertEqual(1, exit_code)
                self.assertIn(f"FAIL {case_id}", stdout.getvalue())

    def test_runner_supports_with_without_skill_comparison(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            answers_path = tmp / "answers.json"
            answers = {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "with_skill": _structured_test_answer(
                            "In A1/B1 the header title is shifted down by about 8 px; point: 116,82."
                        ),
                        "with_skill_run": {"duration_ms": 300.0, "token_count": 200, "transcript": "with.json"},
                        "without_skill": {"findings": [], "summary": "No visible differences."},
                        "without_skill_run": {"duration_ms": 120.0, "token_count": 80, "transcript": "without.json"},
                    }
                ]
            }
            answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
            grading_path = tmp / "grading.json"
            benchmark_path = tmp / "benchmark.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = run_evals_main(
                    [
                        "--answers",
                        str(answers_path),
                        "--case-id",
                        "ios_header_shift",
                        "--compare",
                        "--grading-out",
                        str(grading_path),
                        "--benchmark-out",
                        str(benchmark_path),
                    ]
                )

            output = stdout.getvalue()
            self.assertEqual(0, exit_code)
            self.assertIn("with=1.000", output)
            self.assertIn("without=0.000", output)
            self.assertIn("delta=+1.000", output)
            self.assertIn("duration_ms_delta=+180.0", output)
            self.assertIn("token_count_delta=+120", output)
            grading = json.loads(grading_path.read_text(encoding="utf-8"))
            self.assertIn("comparisons", grading)
            self.assertIn("single_results", grading)
            self.assertIn("run_id", grading)
            self.assertEqual("improved", grading["comparisons"][0]["label"])
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            self.assertEqual(grading["run_id"], benchmark["run_id"])
            self.assertIn("patterns", benchmark)
            self.assertEqual(["ios_header_shift"], benchmark["patterns"]["improved"])
            self.assertEqual([], benchmark["patterns"]["flaky"])

    def test_production_gate_passes_complete_non_regressed_benchmark(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            answers_path = tmp / "answers.json"
            answers = {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "with_skill": _structured_test_answer(
                            "In A1/B1 the header title is shifted down by about 8 px; point: 116,82."
                        ),
                        "with_skill_run": {"duration_ms": 300.0, "token_count": 200},
                        "without_skill": {"findings": [], "summary": "No visible differences."},
                        "without_skill_run": {"duration_ms": 120.0, "token_count": 80},
                    }
                ]
            }
            answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
            benchmark_path = tmp / "benchmark.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = run_evals_main(
                    [
                        "--answers",
                        str(answers_path),
                        "--case-id",
                        "ios_header_shift",
                        "--compare",
                        "--production-gate",
                        "--benchmark-out",
                        str(benchmark_path),
                    ]
                )

            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            self.assertEqual(0, exit_code)
            self.assertIn("Production gate: PASS", stdout.getvalue())
            self.assertTrue(benchmark["production_gate"]["passed"])
            self.assertEqual([], benchmark["production_gate"]["errors"])

    def test_production_gate_fails_when_average_delta_is_too_small(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            answers_path = tmp / "answers.json"
            correct = _structured_test_answer(
                "In A1/B1 the header title is shifted down by about 8 px; point: 116,82."
            )
            answers = {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "with_skill": correct,
                        "with_skill_run": {"duration_ms": 300.0, "token_count": 200},
                        "without_skill": correct,
                        "without_skill_run": {"duration_ms": 120.0, "token_count": 80},
                    }
                ]
            }
            answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
            benchmark_path = tmp / "benchmark.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = run_evals_main(
                    [
                        "--answers",
                        str(answers_path),
                        "--case-id",
                        "ios_header_shift",
                        "--compare",
                        "--production-gate",
                        "--min-score-delta",
                        "0.5",
                        "--benchmark-out",
                        str(benchmark_path),
                    ]
                )

            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            self.assertEqual(1, exit_code)
            self.assertIn("Production gate: FAIL", stdout.getvalue())
            self.assertFalse(benchmark["production_gate"]["passed"])
            self.assertTrue(
                any("average score delta" in error for error in benchmark["production_gate"]["errors"])
            )

    def test_production_gate_requires_baseline_even_when_single_result_passes(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            answers_path = tmp / "answers.json"
            answers = {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "answer": _structured_test_answer(
                            "In A1/B1 the header title is shifted down by about 8 px; point: 116,82."
                        ),
                        "run": {"duration_ms": 300.0, "token_count": 200},
                    }
                ]
            }
            answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
            benchmark_path = tmp / "benchmark.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = run_evals_main(
                    [
                        "--answers",
                        str(answers_path),
                        "--case-id",
                        "ios_header_shift",
                        "--production-gate",
                        "--benchmark-out",
                        str(benchmark_path),
                    ]
                )

            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            self.assertEqual(1, exit_code)
            self.assertIn("missing without_skill baseline", stdout.getvalue())
            self.assertFalse(benchmark["production_gate"]["passed"])

    def test_runner_fails_answer_with_trace_errors(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            answers_path = tmp / "answers.json"
            answers = {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "answer": _structured_test_answer(
                            "In A1/B1 the header title is shifted down by about 8 px; point: 116,82."
                        ),
                        "run": {
                            "duration_ms": 300.0,
                            "token_count": 200,
                            "trace_errors": ["tool calls are forbidden in visual-diff evals"],
                        },
                    }
                ]
            }
            answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = run_evals_main(
                    [
                        "--answers",
                        str(answers_path),
                        "--case-id",
                        "ios_header_shift",
                    ]
                )

            output = stdout.getvalue()
            self.assertEqual(1, exit_code)
            self.assertIn("FAIL ios_header_shift", output)
            self.assertIn("trace errors: tool calls are forbidden", output)

    def test_runner_preserves_source_run_metadata_in_outputs(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            answers_path = tmp / "answers.json"
            answers = {
                "run_id": "codex-20260101T000000Z-abcd1234",
                "run_metadata": {
                    "run_id": "codex-20260101T000000Z-abcd1234",
                    "harness": {"name": "pixel-perfect-design-to-code-evals"},
                },
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "answer": _structured_test_answer(
                            "In A1/B1 the header title is shifted down by about 8 px; point: 116,82."
                        ),
                    }
                ],
            }
            answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
            grading_path = tmp / "grading.json"
            benchmark_path = tmp / "benchmark.json"

            exit_code = run_evals_main(
                [
                    "--answers",
                    str(answers_path),
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
            self.assertEqual(0, exit_code)
            self.assertEqual("codex-20260101T000000Z-abcd1234", grading["run_id"])
            self.assertEqual("codex-20260101T000000Z-abcd1234", benchmark["run_id"])
            self.assertEqual("pixel-perfect-design-to-code-evals", grading["source_run"]["harness"]["name"])

    def test_runner_marks_repeated_attempts_as_flaky(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            answers_path = tmp / "answers.json"
            answers = {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "with_skill_attempts": [
                            {
                                "answer": _structured_test_answer(
                                    "In A1/B1 the header title is shifted down by about 8 px; point: 116,82."
                                ),
                                "run": {"duration_ms": 300.0, "token_count": 200},
                            },
                            {
                                "answer": {"findings": [], "summary": "No visible differences."},
                                "run": {"duration_ms": 250.0, "token_count": 100},
                            },
                        ],
                        "without_skill_attempts": [
                            {
                                "answer": {"findings": [], "summary": "No visible differences."},
                                "run": {"duration_ms": 100.0, "token_count": 50},
                            },
                            {
                                "answer": {"findings": [], "summary": "No visible differences."},
                                "run": {"duration_ms": 110.0, "token_count": 55},
                            },
                        ],
                    }
                ]
            }
            answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
            benchmark_path = tmp / "benchmark.json"

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = run_evals_main(
                    [
                        "--answers",
                        str(answers_path),
                        "--compare",
                        "--case-id",
                        "ios_header_shift",
                        "--benchmark-out",
                        str(benchmark_path),
                    ]
                )

            output = stdout.getvalue()
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            self.assertEqual(1, exit_code)
            self.assertIn("attempts(with/without)=2/2", output)
            self.assertEqual(["ios_header_shift"], benchmark["patterns"]["flaky"])

    def test_runner_treats_with_skill_only_payload_as_single_result_without_compare(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            answers_path = tmp / "answers.json"
            answers = {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "with_skill": _structured_test_answer(
                            "In A1/B1 the header title is shifted down by about 8 px; point: 116,82."
                        ),
                        "with_skill_run": {"duration_ms": 300.0, "token_count": 200},
                    }
                ]
            }
            answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = run_evals_main(
                    [
                        "--answers",
                        str(answers_path),
                        "--case-id",
                        "ios_header_shift",
                    ]
                )

            output = stdout.getvalue()
            self.assertEqual(0, exit_code)
            self.assertIn("PASS ios_header_shift: score=1.000", output)
            self.assertNotIn("with=1.000", output)

    def test_outlier_and_delta_calculation_in_benchmark(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            answers_path = tmp / "answers.json"
            answers = {
                "answers": [
                    {
                        "id": "ios_header_shift",
                        "with_skill": _structured_test_answer(
                            "In A1/B1 the header title is shifted down by about 8 px; point: 116,82."
                        ),
                        "with_skill_run": {"duration_ms": 500, "token_count": 500},
                        "without_skill": {"findings": [], "summary": "No differences."},
                        "without_skill_run": {"duration_ms": 100, "token_count": 60},
                    },
                    {
                        "id": "android_cta_spacing",
                        "with_skill": _structured_test_answer(
                            "In C7/D7 the bottom CTA/button is too high, reducing vertical spacing by 16px; point: 180,682."
                        ),
                        "with_skill_run": {"duration_ms": 300, "token_count": 300},
                        "without_skill": {"findings": [], "summary": "No differences."},
                        "without_skill_run": {"duration_ms": 100, "token_count": 120},
                    },
                ]
            }
            answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
            cases_path = tmp / "cases.json"
            selected_case_ids = {"ios_header_shift", "android_cta_spacing"}
            cases_payload = json.loads((PIXEL_EVALS / "cases.json").read_text(encoding="utf-8"))
            cases_path.write_text(
                json.dumps(
                    {
                        "cases": [
                            case
                            for case in cases_payload["cases"]
                            if case["id"] in selected_case_ids
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            benchmark_path = tmp / "benchmark.json"

            run_evals_main(
                [
                    "--cases",
                    str(cases_path),
                    "--answers",
                    str(answers_path),
                    "--compare",
                    "--benchmark-out",
                    str(benchmark_path),
                ]
            )

            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            self.assertIn("outliers", benchmark)
            self.assertIn("duration_delta_ms", benchmark["outliers"])
            self.assertEqual(2, len(benchmark["outliers"]["duration_delta_ms"]))
            self.assertGreaterEqual(benchmark["with_skill"]["pass_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
