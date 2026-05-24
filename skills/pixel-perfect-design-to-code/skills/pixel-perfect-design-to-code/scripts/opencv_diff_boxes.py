#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy>=1.26",
#   "opencv-python>=4.9",
# ]
# ///
"""Generate raster visual-diff masks, overlays, boxes, and zoom crops with OpenCV.

This self-contained uv script is intended for raster screenshots such as PNG/JPEG.
SVG inputs should use the browser-canvas report.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path


ATTESTATION_SIGNED_FIELDS = (
    "width",
    "height",
    "inputs",
    "ignore_regions",
    "layers",
    "score",
    "boxes",
    "crops",
    "outputs",
)
ATTESTATION_TYPE = "hmac-sha256"
ATTESTATION_VERSION = "pixel-goal/v1"
DEFAULT_ATTESTATION_KEY_ENV = "PIXEL_GOAL_ATTESTATION_KEY"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenCV visual-diff boxes for screenshots.")
    parser.add_argument("--target", required=True, help="Target/design raster screenshot.")
    parser.add_argument("--actual", required=True, help="Actual/implementation raster screenshot.")
    parser.add_argument("--out-dir", required=True, help="Directory for masks, overlay, and crops.")
    parser.add_argument("--prefix", default="diff", help="Output filename prefix.")
    parser.add_argument("--threshold", type=int, default=28, help="RGB max-channel diff threshold.")
    parser.add_argument("--canny-low", type=int, default=40, help="Canny low threshold.")
    parser.add_argument("--canny-high", type=int, default=120, help="Canny high threshold.")
    parser.add_argument("--dilate", type=int, default=4, help="Dilation kernel radius in pixels.")
    parser.add_argument("--merge-gap", type=int, default=14, help="Merge boxes separated by this gap.")
    parser.add_argument("--min-area", type=int, default=20, help="Minimum contour area after dilation.")
    parser.add_argument("--max-boxes", type=int, default=12, help="Maximum boxes to return.")
    parser.add_argument("--crop-padding", type=int, default=16, help="Padding around zoom crops.")
    parser.add_argument(
        "--overlay-alpha",
        type=float,
        default=0.58,
        help="Mask opacity for overlay images, between 0 and 1.",
    )
    parser.add_argument(
        "--ignore-rect",
        action="append",
        default=[],
        metavar="X,Y,W,H",
        help="Rectangle to ignore in scoring and boxes. Repeatable.",
    )
    parser.add_argument("--previous-metadata", help="Previous run metadata JSON for score gating.")
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit nonzero when current score is worse than previous metadata.",
    )
    parser.add_argument(
        "--require-improvement",
        action="store_true",
        help="Exit nonzero unless current score improves over previous metadata.",
    )
    parser.add_argument(
        "--min-improvement",
        type=float,
        default=0.001,
        help="Minimum score delta required by --require-improvement.",
    )
    parser.add_argument(
        "--regression-tolerance",
        type=float,
        default=0.0005,
        help="Allowed score noise before --fail-on-regression treats a run as worse.",
    )
    parser.add_argument(
        "--attestation-key-env",
        default=DEFAULT_ATTESTATION_KEY_ENV,
        help="Environment variable containing the HMAC key used to sign metadata.",
    )
    parser.add_argument(
        "--attestation-key-id",
        default="default",
        help="Non-secret key identifier recorded in metadata attestation.",
    )
    parser.add_argument(
        "--require-attestation-key",
        action="store_true",
        help="Fail unless --attestation-key-env is set and metadata can be signed.",
    )
    args = parser.parse_args(argv)

    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ModuleNotFoundError as exc:
        print(
            "OpenCV tool unavailable: run this self-contained script with uv, "
            "for example `uv run /path/to/opencv_diff_boxes.py ...`.",
            file=sys.stderr,
        )
        return 2

    target = _load_bgr(Path(args.target), cv2, np)
    actual = _load_bgr(Path(args.actual), cv2, np)
    if target.shape != actual.shape:
        print(f"Image sizes differ: target={target.shape}, actual={actual.shape}", file=sys.stderr)
        return 2

    height, width = target.shape[:2]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay_alpha = _clamp_float(args.overlay_alpha, 0.0, 1.0)
    ignore_rects = [_parse_rect(value, width, height) for value in args.ignore_rect]

    threshold_mask, threshold_image = _threshold_diff(target, actual, args.threshold, np)
    edge_mask, edge_image = _edge_diff(target, actual, args.canny_low, args.canny_high, cv2, np)
    strict_diff_image = _strict_diff_visual(target, actual, np)
    structural_heatmap = _structural_heatmap(target, actual, cv2, np)
    _apply_ignore_regions(
        ignore_rects,
        masks=[threshold_mask, edge_mask],
        images=[threshold_image, edge_image, strict_diff_image, structural_heatmap],
    )
    combined_mask = cv2.bitwise_or(threshold_mask, edge_mask)
    if args.dilate > 0:
        kernel_size = args.dilate * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
        combined_mask = cv2.dilate(combined_mask, kernel)
        _apply_ignore_regions(ignore_rects, masks=[combined_mask], images=[])

    boxes = _find_boxes(combined_mask, args.min_area, cv2)
    boxes = _merge_boxes(boxes, args.merge_gap)
    boxes = sorted(boxes, key=lambda box: (box["y"], box["x"]))[: args.max_boxes]
    for index, box in enumerate(boxes, start=1):
        box["mask_id"] = f"M{index}"
        box["point"] = [round(box["x"] + box["width"] / 2), round(box["y"] + box["height"] / 2)]
        box["cells"] = _cells_for_box(box, width, height)

    combined_image = _combined_visual(threshold_image, edge_image, np)
    target_combined_overlay = _alpha_overlay(target, combined_image, overlay_alpha, np)
    threshold_overlay = _alpha_overlay(actual, threshold_image, overlay_alpha, np)
    edge_overlay = _alpha_overlay(actual, edge_image, overlay_alpha, np)
    combined_overlay = _alpha_overlay(actual, combined_image, overlay_alpha, np)
    boxes_overlay = _draw_overlay(combined_overlay, boxes, cv2)
    side_by_side = _side_by_side_image(target, boxes_overlay, cv2, np)
    review_panel = _review_panel_image(target, boxes_overlay, strict_diff_image, structural_heatmap, cv2, np)

    paths = {
        "threshold_mask": out_dir / f"{args.prefix}_threshold.png",
        "edge_mask": out_dir / f"{args.prefix}_edge.png",
        "combined_mask": out_dir / f"{args.prefix}_combined.png",
        "strict_diff": out_dir / f"{args.prefix}_strict_diff.png",
        "structural_heatmap": out_dir / f"{args.prefix}_structural_heatmap.png",
        "target_combined_overlay": out_dir / f"{args.prefix}_target_overlay.png",
        "threshold_overlay": out_dir / f"{args.prefix}_threshold_overlay.png",
        "edge_overlay": out_dir / f"{args.prefix}_edge_overlay.png",
        "combined_overlay": out_dir / f"{args.prefix}_combined_overlay.png",
        "boxes_overlay": out_dir / f"{args.prefix}_boxes.png",
        "side_by_side": out_dir / f"{args.prefix}_side_by_side.png",
        "review_panel": out_dir / f"{args.prefix}_review_panel.png",
        "metadata": out_dir / f"{args.prefix}_metadata.json",
    }
    if ignore_rects:
        paths["region_overlay"] = out_dir / f"{args.prefix}_regions.png"
    cv2.imwrite(str(paths["threshold_mask"]), threshold_image)
    cv2.imwrite(str(paths["edge_mask"]), edge_image)
    cv2.imwrite(str(paths["combined_mask"]), combined_image)
    cv2.imwrite(str(paths["strict_diff"]), strict_diff_image)
    cv2.imwrite(str(paths["structural_heatmap"]), structural_heatmap)
    cv2.imwrite(str(paths["target_combined_overlay"]), target_combined_overlay)
    cv2.imwrite(str(paths["threshold_overlay"]), threshold_overlay)
    cv2.imwrite(str(paths["edge_overlay"]), edge_overlay)
    cv2.imwrite(str(paths["combined_overlay"]), combined_overlay)
    cv2.imwrite(str(paths["boxes_overlay"]), boxes_overlay)
    cv2.imwrite(str(paths["side_by_side"]), side_by_side)
    cv2.imwrite(str(paths["review_panel"]), review_panel)
    if ignore_rects:
        cv2.imwrite(str(paths["region_overlay"]), _region_overlay(actual, ignore_rects, cv2, np))

    crop_records = []
    for box in boxes:
        crop_rect = _padded_crop(box, width, height, args.crop_padding)
        crop_paths = {
            "target": out_dir / f"{args.prefix}_{box['mask_id']}_target.png",
            "actual": out_dir / f"{args.prefix}_{box['mask_id']}_actual.png",
            "diff": out_dir / f"{args.prefix}_{box['mask_id']}_diff.png",
            "overlay": out_dir / f"{args.prefix}_{box['mask_id']}_overlay.png",
            "card": out_dir / f"{args.prefix}_{box['mask_id']}_zoom.png",
        }
        crop_images = {}
        for name, image in (
            ("target", target),
            ("actual", actual),
            ("diff", combined_image),
            ("overlay", combined_overlay),
        ):
            crop = image[
                crop_rect["y"] : crop_rect["y"] + crop_rect["height"],
                crop_rect["x"] : crop_rect["x"] + crop_rect["width"],
            ]
            crop_images[name] = crop
            cv2.imwrite(str(crop_paths[name]), crop)
        cv2.imwrite(
            str(crop_paths["card"]),
            _zoom_card_image(
                crop_images["target"],
                crop_images["actual"],
                crop_images["diff"],
                box["mask_id"],
                cv2,
                np,
            ),
        )
        crop_records.append(
            {
                "mask_id": box["mask_id"],
                "crop": crop_rect,
                "target": str(crop_paths["target"]),
                "actual": str(crop_paths["actual"]),
                "diff": str(crop_paths["diff"]),
                "overlay": str(crop_paths["overlay"]),
                "card": str(crop_paths["card"]),
            }
        )

    payload = {
        "width": width,
        "height": height,
        "inputs": {
            "target": str(Path(args.target)),
            "actual": str(Path(args.actual)),
            "target_sha256": _sha256(Path(args.target)),
            "actual_sha256": _sha256(Path(args.actual)),
        },
        "ignore_regions": ignore_rects,
        "layers": [
            "threshold_mask",
            "edge_mask",
            "combined_mask",
            "strict_diff",
            "structural_heatmap",
            "target_combined_overlay",
            "threshold_overlay",
            "edge_overlay",
            "combined_overlay",
            "boxes_overlay",
            "side_by_side",
            "review_panel",
        ],
        "score": _score_from_masks(
            threshold_mask,
            edge_mask,
            combined_mask,
            len(boxes),
            np,
            previous_metadata=Path(args.previous_metadata) if args.previous_metadata else None,
            fail_on_regression=args.fail_on_regression,
            require_improvement=args.require_improvement,
            min_improvement=args.min_improvement,
            regression_tolerance=args.regression_tolerance,
            previous_attestation_key=(
                os.environ.get(args.attestation_key_env) if args.require_attestation_key else None
            ),
        ),
        "boxes": boxes,
        "crops": crop_records,
        "outputs": {key: str(value) for key, value in paths.items()},
    }
    _attach_attestation(
        payload,
        key_env=args.attestation_key_env,
        key_id=args.attestation_key_id,
        require_key=args.require_attestation_key,
    )
    paths["metadata"].write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 1 if payload["score"].get("gate_failed") else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _attach_attestation(
    payload: dict[str, object],
    *,
    key_env: str,
    key_id: str,
    require_key: bool,
) -> None:
    key = os.environ.get(key_env)
    if not key:
        if require_key:
            raise SystemExit(f"missing attestation key: set {key_env}")
        return
    payload["attestation"] = {
        "type": ATTESTATION_TYPE,
        "version": ATTESTATION_VERSION,
        "key_id": key_id,
        "signed_fields": list(ATTESTATION_SIGNED_FIELDS),
        "signature": _attestation_signature(payload, key),
    }


def _attestation_signature(payload: dict[str, object], key: str) -> str:
    canonical = json.dumps(
        _attestation_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _attestation_payload(payload: dict[str, object]) -> dict[str, object]:
    return {field: payload.get(field) for field in ATTESTATION_SIGNED_FIELDS}


def _attestation_is_valid(payload: dict[str, object], key: str) -> bool:
    attestation = payload.get("attestation")
    if not isinstance(attestation, dict):
        return False
    signature = attestation.get("signature")
    if not isinstance(signature, str):
        return False
    if attestation.get("type") != ATTESTATION_TYPE:
        return False
    if attestation.get("version") != ATTESTATION_VERSION:
        return False
    if attestation.get("signed_fields") != list(ATTESTATION_SIGNED_FIELDS):
        return False
    return hmac.compare_digest(signature, _attestation_signature(payload, key))


def _load_bgr(path: Path, cv2, np):
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise SystemExit(f"Could not read image: {path}")
    if len(image.shape) == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        bgr = image[:, :, :3].astype(np.float32)
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        white = np.full_like(bgr, 255.0)
        return (bgr * alpha + white * (1.0 - alpha)).astype(np.uint8)
    return image[:, :, :3]


def _threshold_diff(target, actual, threshold: int, np):
    diff = np.max(np.abs(target.astype(np.int16) - actual.astype(np.int16)), axis=2)
    mask = (diff >= threshold).astype(np.uint8) * 255
    image = np.zeros((*mask.shape, 3), dtype=np.uint8)
    image[mask > 0] = (42, 42, 255)
    return mask, image


def _edge_diff(target, actual, low: int, high: int, cv2, np):
    target_edges = cv2.Canny(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY), low, high)
    actual_edges = cv2.Canny(cv2.cvtColor(actual, cv2.COLOR_BGR2GRAY), low, high)
    mask = cv2.absdiff(target_edges, actual_edges)
    image = np.zeros((*mask.shape, 3), dtype=np.uint8)
    image[mask > 0] = (21, 204, 250)
    return mask, image


def _strict_diff_visual(target, actual, np):
    diff = np.abs(target.astype(np.int16) - actual.astype(np.int16))
    return np.clip(diff * 4, 0, 255).astype(np.uint8)


def _structural_heatmap(target, actual, cv2, np):
    target_gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
    actual_gray = cv2.cvtColor(actual, cv2.COLOR_BGR2GRAY)
    target_edges = _sobel_magnitude(target_gray, cv2, np)
    actual_edges = _sobel_magnitude(actual_gray, cv2, np)
    diff = cv2.absdiff(target_edges, actual_edges)
    diff = cv2.GaussianBlur(diff, (5, 5), 0)
    if float(diff.max()) > 0:
        normalized = np.clip((diff / diff.max()) * 255, 0, 255).astype(np.uint8)
    else:
        normalized = np.zeros_like(target_gray)
    normalized[normalized < 12] = 0
    color_map = getattr(cv2, "COLORMAP_TURBO", cv2.COLORMAP_JET)
    heatmap = cv2.applyColorMap(normalized, color_map)
    heatmap[normalized == 0] = (0, 0, 0)
    return heatmap


def _sobel_magnitude(gray, cv2, np):
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(grad_x, grad_y).astype(np.float32)


def _alpha_overlay(base, mask_image, alpha: float, np):
    overlay = base.copy().astype(np.float32)
    active = np.any(mask_image > 0, axis=2)
    overlay[active] = overlay[active] * (1.0 - alpha) + mask_image[active].astype(np.float32) * alpha
    return np.clip(overlay, 0, 255).astype(np.uint8)


def _apply_ignore_regions(
    regions: list[dict[str, int]],
    *,
    masks: list,
    images: list,
) -> None:
    for region in regions:
        x, y, width, height = region["x"], region["y"], region["width"], region["height"]
        for mask in masks:
            mask[y : y + height, x : x + width] = 0
        for image in images:
            image[y : y + height, x : x + width] = 0


def _find_boxes(mask, min_area: int, cv2) -> list[dict[str, int]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        area = int(cv2.contourArea(contour))
        x, y, width, height = [int(value) for value in cv2.boundingRect(contour)]
        if area >= min_area and width >= 3 and height >= 3:
            boxes.append({"x": x, "y": y, "width": width, "height": height, "area": area})
    return boxes


def _merge_boxes(boxes: list[dict[str, int]], gap: int) -> list[dict[str, int]]:
    merged = [dict(box) for box in boxes]
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                if _boxes_are_near(merged[i], merged[j], gap):
                    merged[i] = _union_box(merged[i], merged[j])
                    del merged[j]
                    changed = True
                    break
            if changed:
                break
    return merged


def _boxes_are_near(first: dict[str, int], second: dict[str, int], gap: int) -> bool:
    return not (
        first["x"] + first["width"] + gap < second["x"]
        or second["x"] + second["width"] + gap < first["x"]
        or first["y"] + first["height"] + gap < second["y"]
        or second["y"] + second["height"] + gap < first["y"]
    )


def _union_box(first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
    x = min(first["x"], second["x"])
    y = min(first["y"], second["y"])
    right = max(first["x"] + first["width"], second["x"] + second["width"])
    bottom = max(first["y"] + first["height"], second["y"] + second["height"])
    return {
        "x": x,
        "y": y,
        "width": right - x,
        "height": bottom - y,
        "area": first.get("area", 0) + second.get("area", 0),
    }


def _draw_overlay(actual, boxes: list[dict[str, int]], cv2):
    overlay = actual.copy()
    for box in boxes:
        x, y, width, height = box["x"], box["y"], box["width"], box["height"]
        cv2.rectangle(overlay, (x, y), (x + width, y + height), (0, 0, 255), 3)
        label_y = max(16, y - 6)
        cv2.rectangle(overlay, (x, max(0, y - 22)), (x + 38, max(20, y)), (0, 0, 220), -1)
        cv2.putText(
            overlay,
            box["mask_id"],
            (x + 5, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return overlay


def _side_by_side_image(target, actual, cv2, np):
    return _montage(
        [target, actual],
        ["Target", "Actual + masks + boxes"],
        columns=2,
        cv2=cv2,
        np=np,
    )


def _review_panel_image(target, overlay, strict_diff, heatmap, cv2, np):
    return _montage(
        [target, overlay, strict_diff, heatmap],
        ["Target", "Actual + combined mask", "Strict diff", "Structural heatmap"],
        columns=2,
        cv2=cv2,
        np=np,
    )


def _zoom_card_image(target_crop, actual_crop, diff_crop, mask_id: str, cv2, np):
    return _montage(
        [target_crop, actual_crop, diff_crop],
        [f"{mask_id} target", f"{mask_id} actual", f"{mask_id} diff"],
        columns=3,
        cv2=cv2,
        np=np,
    )


def _montage(images: list, labels: list[str], *, columns: int, cv2, np):
    if not images:
        raise ValueError("images must not be empty")
    header = 30
    gap = 14
    panel_width = max(image.shape[1] for image in images)
    panel_height = max(image.shape[0] for image in images)
    rows = (len(images) + columns - 1) // columns
    width = columns * panel_width + (columns - 1) * gap
    height = rows * (panel_height + header) + (rows - 1) * gap
    canvas = np.full((height, width, 3), 245, dtype=np.uint8)
    for index, image in enumerate(images):
        row = index // columns
        column = index % columns
        x = column * (panel_width + gap)
        y = row * (panel_height + header + gap)
        cv2.putText(
            canvas,
            labels[index],
            (x + 8, y + 21),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (24, 24, 24),
            2,
            cv2.LINE_AA,
        )
        panel_y = y + header
        canvas[panel_y : panel_y + image.shape[0], x : x + image.shape[1]] = image
        cv2.rectangle(
            canvas,
            (x, panel_y),
            (x + image.shape[1] - 1, panel_y + image.shape[0] - 1),
            (210, 210, 210),
            1,
        )
    return canvas


def _region_overlay(actual, regions: list[dict[str, int]], cv2, np):
    overlay = actual.copy()
    tint = overlay.copy()
    for region in regions:
        x, y, width, height = region["x"], region["y"], region["width"], region["height"]
        cv2.rectangle(tint, (x, y), (x + width, y + height), (80, 80, 80), -1)
        cv2.rectangle(overlay, (x, y), (x + width, y + height), (0, 215, 255), 2)
        cv2.putText(
            overlay,
            "ignore",
            (x + 5, min(y + 18, y + height - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 215, 255),
            2,
            cv2.LINE_AA,
        )
    return np.clip(overlay * 0.55 + tint * 0.45, 0, 255).astype(np.uint8)


def _combined_visual(threshold_image, edge_image, np):
    combined = threshold_image.copy()
    edge_only = np.all(combined == 0, axis=2) & np.any(edge_image > 0, axis=2)
    combined[edge_only] = edge_image[edge_only]
    return combined


def _score_from_masks(
    threshold_mask,
    edge_mask,
    combined_mask,
    box_count: int,
    np,
    *,
    previous_metadata: Path | None = None,
    fail_on_regression: bool = False,
    require_improvement: bool = False,
    min_improvement: float = 0.001,
    regression_tolerance: float = 0.0005,
    previous_attestation_key: str | None = None,
) -> dict[str, object]:
    total_pixels = int(threshold_mask.size)
    threshold_pixels = int(np.count_nonzero(threshold_mask))
    edge_pixels = int(np.count_nonzero(edge_mask))
    combined_pixels = int(np.count_nonzero(combined_mask))
    score = _score_from_counts(
        total_pixels=total_pixels,
        threshold_pixels=threshold_pixels,
        edge_pixels=edge_pixels,
        combined_pixels=combined_pixels,
        box_count=box_count,
    )
    if previous_metadata is not None:
        previous_score = _read_previous_score(
            previous_metadata,
            attestation_key=previous_attestation_key,
        )
        score.update(
            _score_gate(
                float(score["overall"]),
                previous_score,
                fail_on_regression=fail_on_regression,
                require_improvement=require_improvement,
                min_improvement=min_improvement,
                regression_tolerance=regression_tolerance,
            )
        )
    return score


def _score_from_counts(
    *,
    total_pixels: int,
    threshold_pixels: int,
    edge_pixels: int,
    combined_pixels: int,
    box_count: int,
) -> dict[str, object]:
    if total_pixels <= 0:
        raise ValueError("total_pixels must be positive")
    threshold_ratio = threshold_pixels / total_pixels
    edge_ratio = edge_pixels / total_pixels
    combined_ratio = combined_pixels / total_pixels
    weighted_error = min(1.0, threshold_ratio * 8.0 + edge_ratio * 4.0 + combined_ratio * 2.0)
    return {
        "source": "opencv_diff_boxes",
        "overall": round(max(0.0, 1.0 - weighted_error), 6),
        "threshold_diff_ratio": round(threshold_ratio, 6),
        "edge_diff_ratio": round(edge_ratio, 6),
        "combined_diff_ratio": round(combined_ratio, 6),
        "threshold_pixels": threshold_pixels,
        "edge_pixels": edge_pixels,
        "combined_pixels": combined_pixels,
        "total_pixels": total_pixels,
        "box_count": box_count,
    }


def _read_previous_score(path: Path, *, attestation_key: str | None = None) -> float:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        score = payload["score"]
        if not _score_is_verified(score):
            raise ValueError("previous score metadata is not machine-verified")
        if attestation_key is not None and not _attestation_is_valid(payload, attestation_key):
            raise ValueError("previous score metadata attestation is invalid")
        return float(score["overall"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read previous score from {path}: {exc}") from exc


def _score_is_verified(score: object) -> bool:
    if not isinstance(score, dict) or score.get("source") != "opencv_diff_boxes":
        return False
    required_numbers = (
        "overall",
        "threshold_diff_ratio",
        "edge_diff_ratio",
        "combined_diff_ratio",
        "threshold_pixels",
        "edge_pixels",
        "combined_pixels",
        "total_pixels",
        "box_count",
    )
    for key in required_numbers:
        value = score.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
    return int(score["total_pixels"]) > 0


def _score_gate(
    current_score: float,
    previous_score: float,
    *,
    fail_on_regression: bool,
    require_improvement: bool,
    min_improvement: float,
    regression_tolerance: float,
) -> dict[str, object]:
    delta = current_score - previous_score
    regressed = delta < -regression_tolerance
    improved = delta >= min_improvement
    gate_failed = (fail_on_regression and regressed) or (require_improvement and not improved)
    return {
        "previous_overall": round(previous_score, 6),
        "delta": round(delta, 6),
        "improved": improved,
        "regressed": regressed,
        "gate_failed": gate_failed,
    }


def _padded_crop(box: dict[str, int], width: int, height: int, padding: int) -> dict[str, int]:
    x = max(0, box["x"] - padding)
    y = max(0, box["y"] - padding)
    right = min(width, box["x"] + box["width"] + padding)
    bottom = min(height, box["y"] + box["height"] + padding)
    return {"x": x, "y": y, "width": right - x, "height": bottom - y}


def _cells_for_box(box: dict[str, int], width: int, height: int) -> list[str]:
    columns = "ABCD"
    cell_width = width / 4
    cell_height = height / 8
    left = _clamp(int(box["x"] // cell_width), 0, 3)
    right = _clamp(int((box["x"] + box["width"] - 1) // cell_width), 0, 3)
    top = _clamp(int(box["y"] // cell_height), 0, 7)
    bottom = _clamp(int((box["y"] + box["height"] - 1) // cell_height), 0, 7)
    return [f"{columns[column]}{row + 1}" for row in range(top, bottom + 1) for column in range(left, right + 1)]


def _parse_rect(value: str, image_width: int, image_height: int) -> dict[str, int]:
    try:
        x, y, width, height = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise SystemExit(f"invalid --ignore-rect {value!r}; expected X,Y,W,H") from exc
    if width <= 0 or height <= 0:
        raise SystemExit(f"invalid --ignore-rect {value!r}; width and height must be positive")
    left = _clamp(x, 0, image_width)
    top = _clamp(y, 0, image_height)
    right = _clamp(x + width, 0, image_width)
    bottom = _clamp(y + height, 0, image_height)
    if right <= left or bottom <= top:
        raise SystemExit(f"invalid --ignore-rect {value!r}; rectangle is outside the image")
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _clamp(value: int, low: int, high: int) -> int:
    return min(high, max(low, value))


def _clamp_float(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


if __name__ == "__main__":
    raise SystemExit(main())
