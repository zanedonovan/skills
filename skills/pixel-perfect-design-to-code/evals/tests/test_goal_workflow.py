from __future__ import annotations

import importlib.util
import json
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
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
    / "opencv_diff_boxes.py"
)
HAS_OPENCV = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None


def _load_tool_module():
    spec = importlib.util.spec_from_file_location("opencv_diff_boxes", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load opencv_diff_boxes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GoalWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = _load_tool_module()

    def test_similarity_score_rewards_lower_visual_diff(self) -> None:
        perfect = self.tool._score_from_counts(
            total_pixels=1000,
            threshold_pixels=0,
            edge_pixels=0,
            combined_pixels=0,
            box_count=0,
        )
        noisy = self.tool._score_from_counts(
            total_pixels=1000,
            threshold_pixels=20,
            edge_pixels=30,
            combined_pixels=40,
            box_count=3,
        )

        self.assertEqual(1.0, perfect["overall"])
        self.assertGreater(perfect["overall"], noisy["overall"])
        self.assertEqual(3, noisy["box_count"])

    def test_score_gate_flags_regression_and_missing_improvement(self) -> None:
        regression = self.tool._score_gate(
            0.82,
            0.90,
            fail_on_regression=True,
            require_improvement=True,
            min_improvement=0.001,
            regression_tolerance=0.0005,
        )
        plateau = self.tool._score_gate(
            0.90,
            0.90,
            fail_on_regression=True,
            require_improvement=True,
            min_improvement=0.001,
            regression_tolerance=0.0005,
        )
        improvement = self.tool._score_gate(
            0.91,
            0.90,
            fail_on_regression=True,
            require_improvement=True,
            min_improvement=0.001,
            regression_tolerance=0.0005,
        )

        self.assertTrue(regression["regressed"])
        self.assertTrue(regression["gate_failed"])
        self.assertFalse(plateau["regressed"])
        self.assertTrue(plateau["gate_failed"])
        self.assertTrue(improvement["improved"])
        self.assertFalse(improvement["gate_failed"])

    def test_metadata_attestation_signs_score_payload(self) -> None:
        payload = {
            "width": 10,
            "height": 10,
            "inputs": {"target_sha256": "a", "actual_sha256": "b"},
            "ignore_regions": [],
            "layers": [],
            "score": self.tool._score_from_counts(
                total_pixels=100,
                threshold_pixels=0,
                edge_pixels=0,
                combined_pixels=0,
                box_count=0,
            ),
            "boxes": [],
            "crops": [],
            "outputs": {},
        }
        old_key = os.environ.get("PIXEL_GOAL_ATTESTATION_KEY")
        os.environ["PIXEL_GOAL_ATTESTATION_KEY"] = "test-secret"
        try:
            self.tool._attach_attestation(
                payload,
                key_env="PIXEL_GOAL_ATTESTATION_KEY",
                key_id="test",
                require_key=True,
            )
        finally:
            if old_key is None:
                os.environ.pop("PIXEL_GOAL_ATTESTATION_KEY", None)
            else:
                os.environ["PIXEL_GOAL_ATTESTATION_KEY"] = old_key

        signature = payload["attestation"]["signature"]
        self.assertEqual("hmac-sha256", payload["attestation"]["type"])
        self.assertEqual("test", payload["attestation"]["key_id"])
        self.assertEqual(signature, self.tool._attestation_signature(payload, "test-secret"))
        payload["score"]["overall"] = 0.0
        self.assertNotEqual(signature, self.tool._attestation_signature(payload, "test-secret"))

    def test_previous_score_attestation_is_required_when_key_is_supplied(self) -> None:
        payload = {
            "width": 10,
            "height": 10,
            "inputs": {"target_sha256": "a", "actual_sha256": "b"},
            "ignore_regions": [],
            "layers": [],
            "score": self.tool._score_from_counts(
                total_pixels=100,
                threshold_pixels=0,
                edge_pixels=0,
                combined_pixels=0,
                box_count=0,
            ),
            "boxes": [],
            "crops": [],
            "outputs": {},
        }
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            unsigned = tmp_path / "unsigned.json"
            signed = tmp_path / "signed.json"
            unsigned.write_text(json.dumps(payload), encoding="utf-8")

            old_key = os.environ.get("PIXEL_GOAL_ATTESTATION_KEY")
            os.environ["PIXEL_GOAL_ATTESTATION_KEY"] = "test-secret"
            try:
                self.tool._attach_attestation(
                    payload,
                    key_env="PIXEL_GOAL_ATTESTATION_KEY",
                    key_id="test",
                    require_key=True,
                )
            finally:
                if old_key is None:
                    os.environ.pop("PIXEL_GOAL_ATTESTATION_KEY", None)
                else:
                    os.environ["PIXEL_GOAL_ATTESTATION_KEY"] = old_key
            signed.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(SystemExit) as raised:
                self.tool._read_previous_score(unsigned, attestation_key="test-secret")
            signed_score = self.tool._read_previous_score(signed, attestation_key="test-secret")

        self.assertIn("attestation is invalid", str(raised.exception))
        self.assertEqual(1.0, signed_score)

    @unittest.skipUnless(HAS_OPENCV, "opencv-python and numpy are optional")
    def test_raster_png_jpg_run_writes_agent_review_layers(self) -> None:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target_path = tmp_path / "target.png"
            actual_path = tmp_path / "actual.jpg"
            out_dir = tmp_path / "diff"
            target = np.full((96, 80, 3), 255, dtype=np.uint8)
            actual = target.copy()
            actual[28:58, 24:56] = (0, 0, 220)
            self.assertTrue(cv2.imwrite(str(target_path), target))
            self.assertTrue(cv2.imwrite(str(actual_path), actual))

            with redirect_stdout(StringIO()):
                exit_code = self.tool.main(
                    [
                        "--target",
                        str(target_path),
                        "--actual",
                        str(actual_path),
                        "--out-dir",
                        str(out_dir),
                        "--prefix",
                        "case",
                        "--ignore-rect",
                        "0,0,8,8",
                    ]
                )

            metadata = json.loads((out_dir / "case_metadata.json").read_text(encoding="utf-8"))

            self.assertEqual(0, exit_code)
            self.assertEqual("opencv_diff_boxes", metadata["score"]["source"])
            self.assertGreater(metadata["score"]["combined_pixels"], 0)
            self.assertGreaterEqual(len(metadata["boxes"]), 1)
            self.assertEqual([{"x": 0, "y": 0, "width": 8, "height": 8}], metadata["ignore_regions"])
            for key in (
                "strict_diff",
                "structural_heatmap",
                "target_combined_overlay",
                "threshold_overlay",
                "edge_overlay",
                "combined_overlay",
                "boxes_overlay",
                "side_by_side",
                "review_panel",
                "region_overlay",
            ):
                with self.subTest(key=key):
                    self.assertIn(key, metadata["outputs"])
                    self.assertTrue(Path(metadata["outputs"][key]).is_file())
            self.assertIn("side_by_side", metadata["layers"])
            self.assertIn("review_panel", metadata["layers"])
            self.assertTrue(Path(metadata["crops"][0]["card"]).is_file())


if __name__ == "__main__":
    unittest.main()
