from __future__ import annotations

import importlib.util
import json
import hashlib
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    ROOT
    / "skills"
    / "pixel-perfect-design-to-code"
    / "skills"
    / "pixel-perfect-design-to-code"
    / "scripts"
    / "goal_report.py"
)


def _load_report_module():
    spec = importlib.util.spec_from_file_location("goal_report", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load goal_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _verified_metadata(target: Path, current: Path) -> dict[str, object]:
    return {
        "width": 390,
        "height": 844,
        "inputs": {
            "target_sha256": _sha256(target),
            "actual_sha256": _sha256(current),
        },
        "ignore_regions": [],
        "layers": [],
        "score": {
            "source": "opencv_diff_boxes",
            "overall": 0.99,
            "threshold_diff_ratio": 0.0,
            "edge_diff_ratio": 0.0,
            "combined_diff_ratio": 0.0,
            "threshold_pixels": 0,
            "edge_pixels": 0,
            "combined_pixels": 0,
            "total_pixels": 100,
            "box_count": 0,
        },
        "boxes": [],
        "crops": [],
        "outputs": {},
    }


class GoalReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = _load_report_module()

    def test_report_renders_target_iteration_budget_scores_and_artifacts(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "target.png"
            first = tmp_path / "iter-00.png"
            second = tmp_path / "iter-01.png"
            metadata = tmp_path / "iter-01_metadata.json"
            out = tmp_path / "report.html"
            for path in (target, first, second):
                path.write_bytes(b"image")
            metadata.write_text(
                json.dumps(
                    {
                        "width": 390,
                        "height": 844,
                        "inputs": {
                            "target_sha256": _sha256(target),
                            "actual_sha256": _sha256(second),
                        },
                        "score": {
                            "source": "opencv_diff_boxes",
                            "overall": 0.91,
                            "delta": 0.04,
                            "improved": True,
                            "regressed": False,
                            "gate_failed": False,
                            "box_count": 2,
                            "threshold_diff_ratio": 0.001,
                            "edge_diff_ratio": 0.002,
                            "combined_diff_ratio": 0.003,
                            "threshold_pixels": 10,
                            "edge_pixels": 20,
                            "combined_pixels": 30,
                            "total_pixels": 10000,
                        },
                        "outputs": {"boxes_overlay": str(tmp_path / "boxes.png")},
                    }
                ),
                encoding="utf-8",
            )
            pair_images = self.report.write_review_pair_svgs(
                target=target,
                iterations=[
                    self.report.GoalIteration(0, first),
                    self.report.GoalIteration(1, second, metadata),
                ],
                out_dir=tmp_path / "review-pairs",
                width=390,
                height=844,
            )

            html = self.report.render_goal_report_html(
                target=target,
                iterations=[
                    self.report.GoalIteration(0, first),
                    self.report.GoalIteration(1, second, metadata),
                ],
                max_iterations=5,
                goal="/goal match checkout screen",
                report_path=out,
                width=390,
                height=844,
                pair_images=pair_images,
            )

            pair_svg = pair_images[1].read_text(encoding="utf-8")

        self.assertIn("Goal: /goal match checkout screen", html)
        self.assertIn("Iterations: 2/5", html)
        self.assertIn("Target design", html)
        self.assertIn("Iteration 0", html)
        self.assertIn("Iteration 1", html)
        self.assertIn("Agent side-by-side image", html)
        self.assertIn("iter-01_side_by_side.svg", html)
        self.assertIn('data-agent-review="true"', html)
        self.assertIn('class="mask-canvas target-mask"', html)
        self.assertIn('class="mask-canvas current-mask"', html)
        self.assertIn('class="ruler-overlay"', html)
        self.assertIn("Red marks color/fill changes", html)
        self.assertIn("sobelEdges", html)
        self.assertIn("0.910000", html)
        self.assertIn("0.040000", html)
        self.assertIn("verified", html)
        self.assertIn("Boxes", html)
        self.assertIn("Target design", pair_svg)
        self.assertIn("Current Iteration 1", pair_svg)
        self.assertIn('class="tick-major"', pair_svg)

    def test_report_marks_scores_without_pixel_counts_as_unverified(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "target.svg"
            current = tmp_path / "current.svg"
            metadata = tmp_path / "metadata.json"
            out = tmp_path / "report.html"
            target.write_text("<svg></svg>", encoding="utf-8")
            current.write_text("<svg></svg>", encoding="utf-8")
            metadata.write_text(
                json.dumps(
                    {
                        "width": 390,
                        "height": 844,
                        "score": {
                            "overall": 1.0,
                            "delta": 0.0588,
                            "improved": True,
                            "regressed": False,
                            "gate_failed": False,
                            "box_count": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            html = self.report.render_goal_report_html(
                target=target,
                iterations=[self.report.GoalIteration(0, current, metadata)],
                max_iterations=3,
                goal="/goal smoke",
                report_path=out,
                width=390,
                height=844,
                pair_images={},
            )
            state = self.report.render_goal_state_md(
                target=target,
                iterations=[self.report.GoalIteration(0, current, metadata)],
                max_iterations=3,
                goal="/goal smoke",
                report_path=out,
            )

        self.assertIn("unverified", html)
        self.assertIn("- Latest score: 1.000000 (unverified)", state)
        self.assertIn("- Best iteration: n/a", state)
        self.assertIn("- Best score: n/a", state)

    def test_require_verified_score_rejects_handwritten_score_metadata(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "target.svg"
            current = tmp_path / "current.svg"
            metadata = tmp_path / "metadata.json"
            target.write_text("<svg></svg>", encoding="utf-8")
            current.write_text("<svg></svg>", encoding="utf-8")
            metadata.write_text(json.dumps({"score": {"overall": 1.0}}), encoding="utf-8")

            with self.assertRaises(SystemExit) as raised:
                self.report.main(
                    [
                        "--target",
                        str(target),
                        "--screenshot",
                        str(current),
                        "--metadata",
                        str(metadata),
                        "--width",
                        "390",
                        "--height",
                        "844",
                        "--max-iterations",
                        "3",
                        "--out",
                        str(tmp_path / "report.html"),
                        "--require-verified-score",
                    ]
                )

        self.assertIn("unverified score metadata", str(raised.exception))

    def test_require_verified_score_rejects_forged_score_without_matching_hashes(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "target.svg"
            current = tmp_path / "current.svg"
            metadata = tmp_path / "metadata.json"
            target.write_text("<svg>target</svg>", encoding="utf-8")
            current.write_text("<svg>current</svg>", encoding="utf-8")
            metadata.write_text(
                json.dumps(
                    {
                        "inputs": {
                            "target_sha256": "0" * 64,
                            "actual_sha256": "0" * 64,
                        },
                        "score": {
                            "source": "opencv_diff_boxes",
                            "overall": 1.0,
                            "threshold_diff_ratio": 0.0,
                            "edge_diff_ratio": 0.0,
                            "combined_diff_ratio": 0.0,
                            "threshold_pixels": 0,
                            "edge_pixels": 0,
                            "combined_pixels": 0,
                            "total_pixels": 100,
                            "box_count": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit) as raised:
                self.report.main(
                    [
                        "--target",
                        str(target),
                        "--screenshot",
                        str(current),
                        "--metadata",
                        str(metadata),
                        "--width",
                        "390",
                        "--height",
                        "844",
                        "--max-iterations",
                        "3",
                        "--out",
                        str(tmp_path / "report.html"),
                        "--require-verified-score",
                    ]
                )

        self.assertIn("unverified score metadata", str(raised.exception))

    def test_require_verified_score_requires_state_out_after_metadata_verifies(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "target.png"
            current = tmp_path / "current.png"
            metadata = tmp_path / "metadata.json"
            target.write_bytes(b"target")
            current.write_bytes(b"current")
            metadata.write_text(json.dumps(_verified_metadata(target, current)), encoding="utf-8")

            with self.assertRaises(SystemExit) as raised:
                self.report.main(
                    [
                        "--target",
                        str(target),
                        "--screenshot",
                        str(current),
                        "--metadata",
                        str(metadata),
                        "--width",
                        "390",
                        "--height",
                        "844",
                        "--max-iterations",
                        "3",
                        "--out",
                        str(tmp_path / "report.html"),
                        "--require-verified-score",
                    ]
                )

        self.assertIn("--state-out is required", str(raised.exception))

    def test_require_attestation_rejects_unsigned_metadata(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "target.png"
            current = tmp_path / "current.png"
            metadata = tmp_path / "metadata.json"
            target.write_bytes(b"target")
            current.write_bytes(b"current")
            metadata.write_text(json.dumps(_verified_metadata(target, current)), encoding="utf-8")

            old_key = os.environ.get("PIXEL_GOAL_ATTESTATION_KEY")
            os.environ["PIXEL_GOAL_ATTESTATION_KEY"] = "test-secret"
            try:
                with self.assertRaises(SystemExit) as raised:
                    self.report.main(
                        [
                            "--target",
                            str(target),
                            "--screenshot",
                            str(current),
                            "--metadata",
                            str(metadata),
                            "--width",
                            "390",
                            "--height",
                            "844",
                            "--max-iterations",
                            "3",
                            "--out",
                            str(tmp_path / "report.html"),
                            "--require-verified-score",
                            "--require-attestation",
                        ]
                    )
            finally:
                if old_key is None:
                    os.environ.pop("PIXEL_GOAL_ATTESTATION_KEY", None)
                else:
                    os.environ["PIXEL_GOAL_ATTESTATION_KEY"] = old_key

        self.assertIn("untrusted score attestation", str(raised.exception))

    def test_require_attestation_accepts_signed_metadata(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "target.png"
            current = tmp_path / "current.png"
            metadata = tmp_path / "metadata.json"
            out = tmp_path / "report.html"
            state = tmp_path / "state.md"
            target.write_bytes(b"target")
            current.write_bytes(b"current")
            payload = _verified_metadata(target, current)
            self.report._attach_attestation(payload, key="test-secret", key_id="test")
            metadata.write_text(json.dumps(payload), encoding="utf-8")

            old_key = os.environ.get("PIXEL_GOAL_ATTESTATION_KEY")
            os.environ["PIXEL_GOAL_ATTESTATION_KEY"] = "test-secret"
            try:
                result = self.report.main(
                    [
                        "--target",
                        str(target),
                        "--screenshot",
                        str(current),
                        "--metadata",
                        str(metadata),
                        "--width",
                        "390",
                        "--height",
                        "844",
                        "--max-iterations",
                        "3",
                        "--out",
                        str(out),
                        "--state-out",
                        str(state),
                        "--require-verified-score",
                        "--require-attestation",
                    ]
                )
            finally:
                if old_key is None:
                    os.environ.pop("PIXEL_GOAL_ATTESTATION_KEY", None)
                else:
                    os.environ["PIXEL_GOAL_ATTESTATION_KEY"] = old_key
            report_text = out.read_text(encoding="utf-8")
            state_text = state.read_text(encoding="utf-8")

        self.assertEqual(0, result)
        self.assertIn("attested", report_text)
        self.assertIn("Read this file first after context compaction", state_text)

    def test_state_markdown_preserves_resume_context_after_compaction(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "target.png"
            first = tmp_path / "iter-00.png"
            second = tmp_path / "iter-01.png"
            for path in (target, first, second):
                path.write_bytes(b"image")
            first_metadata = tmp_path / "iter-00_metadata.json"
            second_metadata = tmp_path / "iter-01_metadata.json"
            first_metadata.write_text(json.dumps({"score": {"overall": 0.70}}), encoding="utf-8")
            second_metadata.write_text(
                json.dumps(
                    {
                        "inputs": {
                            "target_sha256": _sha256(target),
                            "actual_sha256": _sha256(second),
                        },
                        "score": {
                            "source": "opencv_diff_boxes",
                            "overall": 0.82,
                            "threshold_diff_ratio": 0.01,
                            "edge_diff_ratio": 0.01,
                            "combined_diff_ratio": 0.01,
                            "threshold_pixels": 1,
                            "edge_pixels": 1,
                            "combined_pixels": 1,
                            "total_pixels": 100,
                            "box_count": 1,
                        }
                    }
                ),
                encoding="utf-8",
            )

            state = self.report.render_goal_state_md(
                target=target,
                iterations=[
                    self.report.GoalIteration(0, first, first_metadata),
                    self.report.GoalIteration(1, second, second_metadata),
                ],
                max_iterations=4,
                goal="/goal match checkout screen",
                report_path=tmp_path / "report.html",
                render_command="npm run screenshot",
                pair_images={1: tmp_path / "review-pairs" / "iter-01_side_by_side.svg"},
                pending_findings=["CTA label is 3 px too low"],
                accepted_changes=["Adjusted header padding"],
                rejected_changes=["Tried reducing global font size; score regressed"],
                ignore_regions=["OS status bar clock"],
                next_step="Fix CTA vertical centering, then rerender iteration 2.",
            )

        self.assertIn("Read this file first after context compaction", state)
        self.assertIn("- Iterations: 2/4", state)
        self.assertIn("- Latest score: 0.820000", state)
        self.assertIn("- Best iteration: 1", state)
        self.assertIn("iter-01_side_by_side.svg", state)
        self.assertIn("CTA label is 3 px too low", state)
        self.assertIn("Tried reducing global font size; score regressed", state)
        self.assertIn("OS status bar clock", state)
        self.assertIn("Fix CTA vertical centering", state)


if __name__ == "__main__":
    unittest.main()
