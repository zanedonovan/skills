from __future__ import annotations

import importlib.util
import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[5]
SKILL = ROOT / "skills" / "pixel-perfect-design-to-code" / "skills" / "pixel-perfect-design-to-code"
OPENCV_TOOL = SKILL / "scripts" / "opencv_diff_boxes.py"
GOAL_REPORT = SKILL / "scripts" / "goal_report.py"


HAS_OPENCV = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.eval
@pytest.mark.integration
@pytest.mark.skipif(not HAS_OPENCV, reason="opencv-python and numpy are optional")
def test_goal_loop_e2e_generates_attested_state_report_and_rejects_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    tool = _load_module("opencv_diff_boxes_e2e", OPENCV_TOOL)
    report = _load_module("goal_report_e2e", GOAL_REPORT)
    monkeypatch.setenv("PIXEL_GOAL_ATTESTATION_KEY", "test-secret")

    target = np.full((120, 160, 3), 255, dtype=np.uint8)
    cv2.rectangle(target, (36, 72), (124, 96), (225, 90, 32), -1)
    cv2.putText(target, "Pay", (64, 89), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    iter0 = np.full((120, 160, 3), 255, dtype=np.uint8)
    cv2.rectangle(iter0, (36, 60), (124, 84), (225, 90, 32), -1)
    cv2.putText(iter0, "Pay", (64, 77), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    iter1 = target.copy()
    regression = np.full((120, 160, 3), 255, dtype=np.uint8)
    cv2.rectangle(regression, (12, 30), (148, 54), (80, 80, 220), -1)

    target_path = tmp_path / "target.png"
    iter0_path = tmp_path / ".pixel-goal" / "iter-00" / "current.png"
    iter1_path = tmp_path / ".pixel-goal" / "iter-01" / "current.png"
    bad_path = tmp_path / ".pixel-goal" / "iter-02" / "current.png"
    for path, image in (
        (target_path, target),
        (iter0_path, iter0),
        (iter1_path, iter1),
        (bad_path, regression),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(path), image)

    with redirect_stdout(StringIO()):
        assert tool.main(
            [
                "--target",
                str(target_path),
                "--actual",
                str(iter0_path),
                "--out-dir",
                str(iter0_path.parent),
                "--prefix",
                "iter-00",
                "--require-attestation-key",
            ]
        ) == 0
        assert tool.main(
            [
                "--target",
                str(target_path),
                "--actual",
                str(iter1_path),
                "--out-dir",
                str(iter1_path.parent),
                "--prefix",
                "iter-01",
                "--previous-metadata",
                str(iter0_path.parent / "iter-00_metadata.json"),
                "--require-improvement",
                "--fail-on-regression",
                "--require-attestation-key",
            ]
        ) == 0
        regression_exit = tool.main(
            [
                "--target",
                str(target_path),
                "--actual",
                str(bad_path),
                "--out-dir",
                str(bad_path.parent),
                "--prefix",
                "iter-02",
                "--previous-metadata",
                str(iter1_path.parent / "iter-01_metadata.json"),
                "--require-improvement",
                "--fail-on-regression",
                "--require-attestation-key",
            ]
        )

    report_path = tmp_path / ".pixel-goal" / "report.html"
    state_path = tmp_path / ".pixel-goal" / "state.md"
    with redirect_stdout(StringIO()):
        report_exit = report.main(
            [
                "--target",
                str(target_path),
                "--screenshot",
                str(iter0_path),
                "--metadata",
                str(iter0_path.parent / "iter-00_metadata.json"),
                "--screenshot",
                str(iter1_path),
                "--metadata",
                str(iter1_path.parent / "iter-01_metadata.json"),
                "--width",
                "160",
                "--height",
                "120",
                "--max-iterations",
                "3",
                "--out",
                str(report_path),
                "--state-out",
                str(state_path),
                "--pair-out-dir",
                str(tmp_path / ".pixel-goal" / "review-pairs"),
                "--require-verified-score",
                "--require-attestation",
                "--accepted-change",
                "Moved CTA button down to target y-position.",
                "--rejected-change",
                "Rejected a later color/position regression.",
                "--next-step",
                "Stop: verified score reached the target without regression.",
            ]
        )

    iter0_metadata = json.loads((iter0_path.parent / "iter-00_metadata.json").read_text())
    iter1_metadata = json.loads((iter1_path.parent / "iter-01_metadata.json").read_text())
    bad_metadata = json.loads((bad_path.parent / "iter-02_metadata.json").read_text())
    state_text = state_path.read_text(encoding="utf-8")
    report_text = report_path.read_text(encoding="utf-8")

    assert regression_exit == 1
    assert report_exit == 0
    assert iter0_metadata["attestation"]["type"] == "hmac-sha256"
    assert iter1_metadata["score"]["improved"] is True
    assert iter1_metadata["score"]["regressed"] is False
    assert bad_metadata["score"]["gate_failed"] is True
    assert bad_metadata["score"]["regressed"] is True
    assert "- Latest iteration: 1" in state_text
    assert "- Best iteration: 1" in state_text
    assert "Moved CTA button down" in state_text
    assert "Rejected a later color/position regression" in state_text
    assert "attested" in report_text
    assert (tmp_path / ".pixel-goal" / "review-pairs" / "iter-01_side_by_side.svg").is_file()
