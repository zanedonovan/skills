from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from eval_suite import PIXEL_EVALS, load_pixel_eval_module
from mobile_grid_overlay.evals import load_answers_json, load_cases_json, public_case_label


ROOT = Path(__file__).resolve().parents[4]
render_side_by_side_html = load_pixel_eval_module("html_report").render_side_by_side_html


class HtmlReportTests(unittest.TestCase):
    def test_report_contains_prompt_and_before_after_grid_images(self) -> None:
        cases = load_cases_json(PIXEL_EVALS / "cases.json")
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )

        html = render_side_by_side_html(cases[:1], template, report_path=PIXEL_EVALS / "side_by_side.html")

        case_label = public_case_label(cases[0].id)
        self.assertIn(case_label, html)
        self.assertNotIn("ios_header_shift", html)
        self.assertIn("You are reviewing two mobile app screenshots for visual parity", html)
        self.assertIn("Target design", html)
        self.assertIn("After: implementation", html)
        self.assertIn(f'alt="Target design for {case_label}"', html)
        self.assertIn(f'src="public/{case_label}_mock.png"', html)
        self.assertIn(f'src="public/{case_label}_actual.png"', html)
        self.assertIn("estimate pixel deltas", html)
        self.assertNotIn("Title baseline is lower", html)

    def test_report_contains_agent_output_when_answers_are_provided(self) -> None:
        cases = load_cases_json(PIXEL_EVALS / "cases.json")
        answers = load_answers_json(PIXEL_EVALS / "sample_answers.json")
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )

        html = render_side_by_side_html(
            cases[:1],
            template,
            report_path=PIXEL_EVALS / "side_by_side.html",
            answers=answers,
        )

        self.assertIn("Agent Output", html)
        self.assertIn("PASS · score=1.000", html)

    def test_report_embeds_live_agent_dialog_from_transcript(self) -> None:
        cases = load_cases_json(PIXEL_EVALS / "cases.json")
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )
        with TemporaryDirectory() as tmp_dir:
            transcripts_dir = Path(tmp_dir)
            transcript = {
                "run_mode": "with_skill",
                "command": [
                    "codex",
                    "exec",
                    "--image",
                    str(PIXEL_EVALS / "public" / "case-8bd6075a_mock_clean.png"),
                    "--image",
                    str(PIXEL_EVALS / "review_artifacts" / "case-8bd6075a" / "case-8bd6075a_M1_zoom.png"),
                    "-",
                ],
                "prompt": "full prompt sent to agent",
                "duration_ms": 123.4,
                "output_raw": '{"findings":[],"summary":"ok"}',
            }
            (transcripts_dir / "ios_header_shift_with_skill_last_message.json").write_text(
                json.dumps(transcript),
                encoding="utf-8",
            )

            html = render_side_by_side_html(
                cases[:1],
                template,
                report_path=PIXEL_EVALS / "index.html",
                transcripts_dir=transcripts_dir,
            )

        self.assertIn("Live Agent Dialog", html)
        self.assertIn("full prompt sent to agent", html)
        self.assertIn("case-8bd6075a_M1_zoom.png", html)
        self.assertIn("&quot;summary&quot;:&quot;ok&quot;", html)

    def test_report_overlays_cell_boxes_precise_points_and_exclusion_mask(self) -> None:
        cases = load_cases_json(PIXEL_EVALS / "cases.json")
        answers = load_answers_json(PIXEL_EVALS / "sample_answers.json")
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )

        html = render_side_by_side_html(
            cases[:1],
            template,
            report_path=PIXEL_EVALS / "side_by_side.html",
            answers=answers,
        )

        self.assertIn("Cell Markers", html)
        self.assertIn('class="cell-box expected" data-marker-kind="expected" data-cell="A1"', html)
        self.assertIn('class="cell-box agent" data-marker-kind="agent" data-cell="A1"', html)
        self.assertIn('class="cell-box expected" data-marker-kind="expected" data-cell="B1"', html)
        self.assertIn('class="cell-box agent" data-marker-kind="agent" data-cell="B1"', html)
        self.assertIn("left:0.00%;top:0.00%;width:25.00%;height:12.50%", html)
        self.assertIn("left:25.00%;top:0.00%;width:25.00%;height:12.50%", html)
        self.assertIn('class="target-point expected"', html)
        self.assertIn('class="target-point agent"', html)
        self.assertIn('data-target-kind="expected" data-label="expected"', html)
        self.assertIn('data-target-kind="agent" data-label="agent"', html)
        self.assertIn('class="exclusion-mask"', html)
        self.assertIn('class="mask-fill"', html)

    def test_report_contains_strict_diff_mask_using_clean_images(self) -> None:
        cases = load_cases_json(PIXEL_EVALS / "cases.json")
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )

        html = render_side_by_side_html(
            cases[:1],
            template,
            report_path=PIXEL_EVALS / "side_by_side.html",
        )

        case_label = public_case_label(cases[0].id)
        self.assertIn("Strict diff mask (no grid)", html)
        self.assertIn('class="diff-frame"', html)
        self.assertIn('class="diff-top"', html)
        self.assertIn("mix-blend-mode: difference", html)
        self.assertIn(f'src="public/{case_label}_mock_clean.png"', html)
        self.assertIn(f'src="public/{case_label}_actual_clean.png"', html)

    def test_report_contains_separate_review_layers_for_llm_grounding(self) -> None:
        cases = load_cases_json(PIXEL_EVALS / "cases.json")
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )

        html = render_side_by_side_html(
            cases[:1],
            template,
            report_path=PIXEL_EVALS / "side_by_side.html",
        )

        case_label = public_case_label(cases[0].id)
        self.assertIn("Visual Review Layers", html)
        self.assertIn("review-layers", html)
        self.assertIn("Threshold diff mask", html)
        self.assertIn("Diff boxes (M1, M2...)", html)
        self.assertIn("Edge/shape diff", html)
        self.assertIn("Structural heatmap", html)
        self.assertIn("Zoom crops", html)
        if "static-review-layers" in html:
            self.assertIn(f"review_artifacts/{case_label}/{case_label}_threshold.png", html)
            self.assertIn(f"review_artifacts/{case_label}/{case_label}_boxes.png", html)
            self.assertIn(f"review_artifacts/{case_label}/{case_label}_edge.png", html)
            self.assertIn(f"review_artifacts/{case_label}/{case_label}_structural_heatmap.png", html)
            self.assertIn(f"review_artifacts/{case_label}/{case_label}_M1_zoom.png", html)
        else:
            self.assertIn('data-diff-review="true"', html)
            self.assertIn(f'data-mock-src="public/{case_label}_mock_clean.png"', html)
            self.assertIn(f'data-actual-src="public/{case_label}_actual_clean.png"', html)
            self.assertIn('class="threshold-canvas"', html)
            self.assertIn('class="boxed-canvas"', html)
            self.assertIn('class="edge-canvas"', html)
            self.assertIn('class="structure-canvas"', html)
            self.assertIn('class="zoom-cards"', html)
            self.assertIn('class="mask-metadata"', html)
            self.assertIn("combineMasks", html)
            self.assertIn("buildEdgeDiff", html)
        self.assertIn('class="screenshot-mask-overlay target-mask-overlay"', html)
        self.assertIn('class="screenshot-mask-overlay actual-mask-overlay"', html)
        self.assertIn("drawScreenshotMaskOverlays", html)

    def test_report_contains_region_mode_overlay(self) -> None:
        cases = load_cases_json(PIXEL_EVALS / "cases.json")
        template = (PIXEL_EVALS / "prompts" / "mobile_visual_diff.md").read_text(
            encoding="utf-8"
        )

        html = render_side_by_side_html(
            cases[:1],
            template,
            report_path=PIXEL_EVALS / "side_by_side.html",
        )

        self.assertIn("Region mode overlay", html)
        case_label = public_case_label(cases[0].id)
        if "static-review-layers" in html:
            self.assertIn(f"review_artifacts/{case_label}/{case_label}_regions.png", html)
        else:
            self.assertIn('class="region-mode-layer"', html)
            self.assertIn('data-region-mode="ignore"', html)
            self.assertIn('data-region-mode="strict"', html)


if __name__ == "__main__":
    unittest.main()
