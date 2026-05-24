#!/usr/bin/env python3
"""Render a pixel-perfect /goal iteration report."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


@dataclass(frozen=True)
class GoalIteration:
    index: int
    screenshot: Path
    metadata: Path | None = None


@dataclass(frozen=True)
class ScoreRecord:
    overall: float
    verified: bool
    attested: bool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a HTML report for /goal iterations.")
    parser.add_argument("--target", required=True, help="Target/design screenshot.")
    parser.add_argument("--screenshot", action="append", required=True, help="Iteration screenshot. Repeatable.")
    parser.add_argument("--metadata", action="append", default=[], help="Iteration metadata JSON. Repeatable.")
    parser.add_argument("--out", required=True, help="Output HTML report path.")
    parser.add_argument("--state-out", help="Optional Markdown state file for context-resume.")
    parser.add_argument("--goal", default="Pixel-perfect match against target design.")
    parser.add_argument("--max-iterations", type=int, required=True, help="Iteration budget requested by /goal.")
    parser.add_argument("--width", type=int, help="Screenshot viewport width for ruler overlays.")
    parser.add_argument("--height", type=int, help="Screenshot viewport height for ruler overlays.")
    parser.add_argument(
        "--pair-out-dir",
        help="Directory for agent-facing side-by-side SVG images. Defaults to <report parent>/review-pairs.",
    )
    parser.add_argument("--render-command", default="", help="Command used to re-render implementation screenshots.")
    parser.add_argument("--finding", action="append", default=[], help="Pending finding to preserve in state.md.")
    parser.add_argument("--accepted-change", action="append", default=[], help="Accepted code change to preserve in state.md.")
    parser.add_argument("--rejected-change", action="append", default=[], help="Rejected/regressed attempt to preserve in state.md.")
    parser.add_argument("--ignore-region", action="append", default=[], help="Dynamic/ignored region to preserve in state.md.")
    parser.add_argument("--next-step", default="", help="Next action for resume after context compaction.")
    parser.add_argument(
        "--require-verified-score",
        action="store_true",
        help="Reject metadata whose score was not produced by the OpenCV diff script.",
    )
    parser.add_argument(
        "--require-attestation",
        action="store_true",
        help="Reject metadata not signed with the HMAC key from --attestation-key-env.",
    )
    parser.add_argument(
        "--attestation-key-env",
        default=DEFAULT_ATTESTATION_KEY_ENV,
        help="Environment variable containing the HMAC key used to verify metadata.",
    )
    args = parser.parse_args(argv)

    screenshots = [Path(path) for path in args.screenshot]
    metadata_paths = [Path(path) for path in args.metadata]
    if len(metadata_paths) > len(screenshots):
        raise SystemExit("metadata count cannot exceed screenshot count")

    target_path = Path(args.target)
    iterations = [
        GoalIteration(index=index, screenshot=screenshot, metadata=_metadata_at(metadata_paths, index))
        for index, screenshot in enumerate(screenshots)
    ]
    if args.require_verified_score or args.require_attestation:
        _require_verified_scores(
            target_path,
            iterations,
            require_attestation=args.require_attestation,
            attestation_key_env=args.attestation_key_env,
        )
        if not args.state_out:
            raise SystemExit("--state-out is required when verified score gates are enabled")
    out_path = Path(args.out)
    resolved_width, resolved_height = _report_size(iterations, args.width, args.height)
    pair_out_dir = Path(args.pair_out_dir) if args.pair_out_dir else out_path.parent / "review-pairs"
    pair_images = write_review_pair_svgs(
        target=target_path,
        iterations=iterations,
        out_dir=pair_out_dir,
        width=resolved_width,
        height=resolved_height,
    )
    html_text = render_goal_report_html(
        target=target_path,
        iterations=iterations,
        max_iterations=args.max_iterations,
        goal=args.goal,
        report_path=out_path,
        width=resolved_width,
        height=resolved_height,
        pair_images=pair_images,
        attestation_key_env=args.attestation_key_env,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")
    if args.state_out:
        state_path = Path(args.state_out)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            render_goal_state_md(
                target=target_path,
                iterations=iterations,
                max_iterations=args.max_iterations,
                goal=args.goal,
                report_path=out_path,
                render_command=args.render_command,
                pair_images=pair_images,
                attestation_key_env=args.attestation_key_env,
                pending_findings=args.finding,
                accepted_changes=args.accepted_change,
                rejected_changes=args.rejected_change,
                ignore_regions=args.ignore_region,
                next_step=args.next_step,
            ),
            encoding="utf-8",
        )
    print(f"Report: {out_path}")
    return 0


def render_goal_report_html(
    *,
    target: Path,
    iterations: list[GoalIteration],
    max_iterations: int,
    goal: str,
    report_path: Path,
    width: int | None = None,
    height: int | None = None,
    pair_images: dict[int, Path] | None = None,
    attestation_key_env: str = DEFAULT_ATTESTATION_KEY_ENV,
) -> str:
    resolved_width, resolved_height = _report_size(iterations, width, height)
    pair_images = pair_images or {}
    cards = "\n".join(
        _iteration_card(
            iteration,
            target=target,
            report_path=report_path,
            width=resolved_width,
            height=resolved_height,
            pair_image=pair_images.get(iteration.index),
            attestation_key_env=attestation_key_env,
        )
        for iteration in iterations
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pixel Perfect Goal Report</title>
  <style>
    body {{ margin: 0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f9; color: #17202a; }}
    header {{ padding: 20px 24px; background: #ffffff; border-bottom: 1px solid #d9dee7; }}
    main {{ padding: 20px 24px 32px; }}
    h1 {{ margin: 0 0 6px; font-size: 22px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; letter-spacing: 0; }}
    .meta {{ color: #536170; }}
    .target, .iteration {{ background: #ffffff; border: 1px solid #d9dee7; border-radius: 8px; padding: 14px; }}
    .agent-note {{ margin: 10px 0 18px; color: #536170; }}
    .iterations {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
    .review-pair {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; align-items: start; }}
    .review-frame {{ position: relative; width: fit-content; max-width: 100%; background: #eef1f5; border: 1px solid #d9dee7; border-radius: 6px; overflow: hidden; }}
    .review-frame figcaption {{ margin: 0; padding: 6px 8px; color: #536170; font-size: 12px; font-weight: 700; }}
    .shot {{ display: block; width: 100%; max-height: 620px; object-fit: contain; background: #eef1f5; }}
    .mask-canvas, .ruler-overlay {{ position: absolute; left: 0; right: 0; bottom: 0; width: 100%; pointer-events: none; }}
    .mask-canvas {{ top: 28px; height: calc(100% - 28px); mix-blend-mode: multiply; opacity: .74; }}
    .ruler-overlay {{ top: 28px; height: calc(100% - 28px); }}
    .ruler-bg {{ fill: #020617; fill-opacity: .72; }}
    .tick-minor {{ stroke: #ffffff; stroke-opacity: .46; stroke-width: .7; vector-effect: non-scaling-stroke; }}
    .tick-major {{ stroke: #facc15; stroke-opacity: .96; stroke-width: 1.1; vector-effect: non-scaling-stroke; }}
    .macro-line {{ stroke: #facc15; stroke-opacity: .65; stroke-width: 1; vector-effect: non-scaling-stroke; }}
    .ruler-label {{ font: 800 10px system-ui, sans-serif; stroke: #020617; stroke-width: 2.4; paint-order: stroke; fill: #ffffff; }}
    .overlay-legend {{ position: absolute; left: 8px; bottom: 8px; padding: 3px 6px; border-radius: 4px; background: rgba(15, 23, 42, .78); color: #ffffff; font-size: 11px; font-weight: 700; }}
    .score {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 10px 0 12px; }}
    .metric {{ background: #f3f5f8; border-radius: 6px; padding: 8px; }}
    .metric strong {{ display: block; font-size: 12px; color: #536170; font-weight: 600; }}
    .bad {{ color: #b42318; font-weight: 700; }}
    .good {{ color: #067647; font-weight: 700; }}
    .artifacts {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .artifact img {{ width: 100%; max-height: 240px; object-fit: contain; background: #101828; border-radius: 4px; }}
    .artifact span {{ display: block; margin-bottom: 4px; color: #536170; font-size: 12px; }}
    .crop-grid {{ display: grid; gap: 10px; margin-top: 12px; }}
    .crop-card {{ background: #f3f5f8; border-radius: 6px; padding: 8px; }}
    .crop-card strong {{ display: block; margin-bottom: 6px; color: #536170; font-size: 12px; }}
    .crop-triptych {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }}
    .crop-triptych img {{ width: 100%; max-height: 150px; object-fit: contain; background: #101828; border-radius: 4px; }}
    .crop-triptych span {{ display: block; margin-bottom: 3px; color: #536170; font-size: 11px; }}
    .crop-card-image img {{ width: 100%; max-height: 180px; object-fit: contain; background: #101828; border-radius: 4px; }}
    .crop-card-image span {{ display: block; margin-bottom: 3px; color: #536170; font-size: 11px; }}
    .pair-preview {{ margin: 0 0 12px; }}
    .pair-preview figcaption {{ margin: 0 0 6px; color: #536170; font-size: 12px; font-weight: 700; }}
    .pair-shot {{ width: 100%; max-height: 520px; object-fit: contain; background: #eef1f5; border: 1px solid #d9dee7; border-radius: 6px; }}
  </style>
</head>
<body>
  <header>
    <h1>Pixel Perfect Goal Report</h1>
    <div class="meta">Goal: {html.escape(goal)}</div>
    <div class="meta">Iterations: {len(iterations)}/{max_iterations}</div>
  </header>
  <main>
    <p class="agent-note">Each iteration shows the target and current screenshot with the same ruler grid and diff mask overlaid directly on the images. Red marks color/fill changes; yellow marks edge, shape, typography, radius, and alignment changes.</p>
    <section class="iterations">
      {cards}
    </section>
  </main>
  <script>{_mask_script()}</script>
</body>
</html>
"""


def render_goal_state_md(
    *,
    target: Path,
    iterations: list[GoalIteration],
    max_iterations: int,
    goal: str,
    report_path: Path,
    render_command: str = "",
    pair_images: dict[int, Path] | None = None,
    pending_findings: list[str] | None = None,
    accepted_changes: list[str] | None = None,
    rejected_changes: list[str] | None = None,
    ignore_regions: list[str] | None = None,
    next_step: str = "",
    attestation_key_env: str = DEFAULT_ATTESTATION_KEY_ENV,
) -> str:
    scored = [
        (
            iteration,
            _score_record(
                _load_metadata(iteration.metadata),
                target=target,
                actual=iteration.screenshot,
                attestation_key_env=attestation_key_env,
            ),
        )
        for iteration in iterations
    ]
    scored_iterations = [(iteration, score) for iteration, score in scored if score is not None]
    latest_iteration = iterations[-1] if iterations else None
    latest_score = scored_iterations[-1][1] if scored_iterations else None
    verified_iterations = [
        (iteration, score) for iteration, score in scored_iterations if score.verified
    ]
    best_iteration, best_score = max(
        verified_iterations,
        key=lambda item: item[1].overall,
        default=(None, None),
    )
    pending_findings = pending_findings or []
    accepted_changes = accepted_changes or []
    rejected_changes = rejected_changes or []
    ignore_regions = ignore_regions or []
    pair_images = pair_images or {}

    lines = [
        "# Pixel Perfect Goal State",
        "",
        "Read this file first after context compaction. It is the compact handoff for the active `/goal` loop.",
        "",
        f"- Goal: {goal}",
        f"- Target: {target}",
        f"- Report: {report_path}",
        f"- Iterations: {len(iterations)}/{max_iterations}",
        f"- Latest iteration: {_iteration_label(latest_iteration)}",
        f"- Latest score: {_state_score(latest_score)}",
        f"- Best iteration: {_iteration_label(best_iteration)}",
        f"- Best score: {_state_score(best_score)}",
    ]
    if render_command:
        lines.append(f"- Render command: `{render_command}`")
    lines.extend(["", "## Iteration Artifacts"])
    for iteration, score in scored:
        lines.append(
            f"- Iteration {iteration.index}: screenshot `{iteration.screenshot}`; "
            f"side-by-side `{pair_images.get(iteration.index, '')}`; "
            f"metadata `{iteration.metadata or ''}`; score {_state_score(score)}"
        )
    lines.extend(["", "## Accepted Changes"])
    lines.extend(_bullet_lines(accepted_changes, empty="No accepted changes recorded yet."))
    lines.extend(["", "## Rejected Or Regressed Attempts"])
    lines.extend(_bullet_lines(rejected_changes, empty="No rejected attempts recorded yet."))
    lines.extend(["", "## Pending Findings"])
    lines.extend(_bullet_lines(pending_findings, empty="No pending findings recorded."))
    lines.extend(["", "## Ignored Or Dynamic Regions"])
    lines.extend(_bullet_lines(ignore_regions, empty="No ignored regions recorded."))
    lines.extend(["", "## Resume"])
    lines.append(next_step or "Render the next implementation screenshot, compare against target, and continue only if score improves without regression.")
    lines.append("")
    return "\n".join(lines)


def _iteration_card(
    iteration: GoalIteration,
    *,
    target: Path,
    report_path: Path,
    width: int | None,
    height: int | None,
    pair_image: Path | None = None,
    attestation_key_env: str = DEFAULT_ATTESTATION_KEY_ENV,
) -> str:
    metadata = _load_metadata(iteration.metadata)
    score = metadata.get("score", {}) if isinstance(metadata, dict) else {}
    score_record = _score_record(
        metadata,
        target=target,
        actual=iteration.screenshot,
        attestation_key_env=attestation_key_env,
    )
    artifacts = _artifact_images(metadata, report_path)
    crops = _crop_images(metadata, report_path)
    pair_preview = _pair_preview(pair_image, report_path)
    score_html = _score_block(
        score,
        verified=score_record.verified if score_record else False,
        attested=score_record.attested if score_record else False,
    )
    return f"""<article class="iteration">
  <h2>Iteration {iteration.index}</h2>
  {pair_preview}
  <div class="review-pair" data-agent-review="true" data-width="{width or ''}" data-height="{height or ''}" data-target-src="{_href(target, report_path)}" data-current-src="{_href(iteration.screenshot, report_path)}">
    {_review_frame("Target design", target, report_path, width, height, "target")}
    {_review_frame(f"Current iteration {iteration.index}", iteration.screenshot, report_path, width, height, "current")}
  </div>
  {score_html}
  {artifacts}
  {crops}
</article>"""


def write_review_pair_svgs(
    *,
    target: Path,
    iterations: list[GoalIteration],
    out_dir: Path,
    width: int | None,
    height: int | None,
) -> dict[int, Path]:
    if not width or not height:
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[int, Path] = {}
    for iteration in iterations:
        out_path = out_dir / f"iter-{iteration.index:02d}_side_by_side.svg"
        out_path.write_text(
            render_review_pair_svg(
                target=target,
                current=iteration.screenshot,
                width=width,
                height=height,
                svg_path=out_path,
                label=f"Iteration {iteration.index}",
            ),
            encoding="utf-8",
        )
        outputs[iteration.index] = out_path
    return outputs


def render_review_pair_svg(
    *,
    target: Path,
    current: Path,
    width: int,
    height: int,
    svg_path: Path,
    label: str,
) -> str:
    header_h = 32
    gutter = 20
    total_width = width * 2 + gutter
    total_height = height + header_h
    current_x = width + gutter
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="{total_height}" viewBox="0 0 {total_width} {total_height}" role="img">
  <title>Agent side-by-side review {html.escape(label)}</title>
  <defs><style>
    .ruler-bg{{fill:#020617;fill-opacity:.72}}
    .tick-minor{{stroke:#ffffff;stroke-opacity:.46;stroke-width:.7;vector-effect:non-scaling-stroke}}
    .tick-major{{stroke:#facc15;stroke-opacity:.96;stroke-width:1.1;vector-effect:non-scaling-stroke}}
    .macro-line{{stroke:#facc15;stroke-opacity:.65;stroke-width:1;vector-effect:non-scaling-stroke}}
    .ruler-label{{font:800 10px system-ui,sans-serif;stroke:#020617;stroke-width:2.4;paint-order:stroke;fill:#ffffff}}
  </style></defs>
  <rect x="0" y="0" width="{total_width}" height="{total_height}" fill="#f8fafc" />
  <text x="0" y="21" font-family="system-ui, sans-serif" font-size="15" font-weight="800" fill="#111827">Target design</text>
  <text x="{current_x}" y="21" font-family="system-ui, sans-serif" font-size="15" font-weight="800" fill="#111827">Current {html.escape(label)}</text>
  <image href="{_href(target, svg_path)}" x="0" y="{header_h}" width="{width}" height="{height}" preserveAspectRatio="none" />
  <image href="{_href(current, svg_path)}" x="{current_x}" y="{header_h}" width="{width}" height="{height}" preserveAspectRatio="none" />
  {_ruler_overlay_svg(0, header_h, width, height)}
  {_ruler_overlay_svg(current_x, header_h, width, height)}
  <text x="8" y="{total_height - 10}" font-family="system-ui, sans-serif" font-size="12" font-weight="800" fill="#ffffff" stroke="#020617" stroke-width="3" paint-order="stroke">side-by-side image for agent context: target vs current, same rulers</text>
</svg>
"""


def _pair_preview(pair_image: Path | None, report_path: Path) -> str:
    if pair_image is None:
        return ""
    href = _href(pair_image, report_path)
    return f"""<figure class="pair-preview">
  <figcaption>Agent side-by-side image</figcaption>
  <img class="pair-shot" src="{href}" alt="Agent side-by-side review image">
</figure>"""


def _review_frame(
    label: str,
    screenshot: Path,
    report_path: Path,
    width: int | None,
    height: int | None,
    kind: str,
) -> str:
    canvas_attrs = _size_attrs(width, height)
    return f"""<figure class="review-frame">
  <figcaption>{html.escape(label)}</figcaption>
  <img class="shot {kind}-shot" src="{_href(screenshot, report_path)}" alt="{html.escape(label)}">
  <canvas class="mask-canvas {kind}-mask" {canvas_attrs} aria-label="{html.escape(label)} diff mask overlay"></canvas>
  {_ruler_overlay(width, height)}
  <span class="overlay-legend">rulers + mask</span>
</figure>"""


def _score_block(
    score: dict[str, Any],
    *,
    verified: bool | None = None,
    attested: bool = False,
) -> str:
    if not score:
        return '<div class="meta">No score metadata.</div>'
    status = "regressed" if score.get("regressed") else "improved" if score.get("improved") else "baseline"
    status_class = "bad" if score.get("regressed") or score.get("gate_failed") else "good"
    verified = _score_fields_verified(score) if verified is None else verified
    verified_class = "good" if verified else "bad"
    verified_label = "attested" if verified and attested else "verified" if verified else "unverified"
    return f"""<div class="score">
  <div class="metric"><strong>score</strong>{_fmt(score.get("overall"))}</div>
  <div class="metric"><strong>delta</strong>{_fmt(score.get("delta"))}</div>
  <div class="metric"><strong>boxes</strong>{html.escape(str(score.get("box_count", "")))}</div>
  <div class="metric"><strong>gate</strong><span class="{status_class}">{html.escape(status)}</span></div>
  <div class="metric"><strong>verification</strong><span class="{verified_class}">{verified_label}</span></div>
</div>"""


def _artifact_images(metadata: dict[str, Any], report_path: Path) -> str:
    outputs = metadata.get("outputs") if isinstance(metadata, dict) else None
    if not isinstance(outputs, dict):
        return ""
    wanted = (
        ("review_panel", "Review Panel"),
        ("side_by_side", "Side By Side"),
        ("boxes_overlay", "Boxes"),
        ("combined_overlay", "Combined Overlay"),
        ("target_combined_overlay", "Target Overlay"),
        ("strict_diff", "Strict Diff"),
        ("structural_heatmap", "Structural Heatmap"),
        ("combined_mask", "Combined Mask"),
        ("threshold_mask", "Threshold"),
        ("edge_mask", "Edges"),
        ("threshold_overlay", "Threshold Overlay"),
        ("edge_overlay", "Edge Overlay"),
        ("region_overlay", "Ignored Regions"),
    )
    images = []
    for key, label in wanted:
        path = outputs.get(key)
        if path:
            images.append(
                f'<div class="artifact"><span>{html.escape(label)}</span>'
                f'<img src="{_href(Path(path), report_path)}" alt="{html.escape(label)}"></div>'
            )
    if not images:
        return ""
    return '<div class="artifacts">' + "\n".join(images) + "</div>"


def _crop_images(metadata: dict[str, Any], report_path: Path) -> str:
    crops = metadata.get("crops") if isinstance(metadata, dict) else None
    if not isinstance(crops, list):
        return ""
    cards = []
    for crop in crops:
        if not isinstance(crop, dict):
            continue
        mask_id = html.escape(str(crop.get("mask_id", "Crop")))
        images = []
        for key, label in (("target", "Target"), ("actual", "Current"), ("diff", "Diff"), ("overlay", "Overlay")):
            path = crop.get(key)
            if path:
                images.append(
                    f'<div><span>{label}</span><img src="{_href(Path(path), report_path)}" '
                    f'alt="{label} crop for {mask_id}"></div>'
                )
        if images:
            card_path = crop.get("card")
            card_html = ""
            if card_path:
                card_html = (
                    f'<div class="crop-card-image"><span>Zoom card</span>'
                    f'<img src="{_href(Path(card_path), report_path)}" alt="Zoom card for {mask_id}"></div>'
                )
            cards.append(
                f'<div class="crop-card"><strong>{mask_id} zoom crop</strong>'
                f'{card_html}<div class="crop-triptych">{"".join(images)}</div></div>'
            )
    if not cards:
        return ""
    return '<div class="crop-grid">' + "\n".join(cards) + "</div>"


def _load_metadata(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _metadata_at(paths: list[Path], index: int) -> Path | None:
    return paths[index] if index < len(paths) else None


def _href(path: Path, report_path: Path) -> str:
    try:
        value = os.path.relpath(path, report_path.parent)
    except ValueError:
        value = str(path)
    return html.escape(value)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    if value is None:
        return ""
    return html.escape(str(value))


def _report_size(
    iterations: list[GoalIteration],
    width: int | None,
    height: int | None,
) -> tuple[int | None, int | None]:
    if width and height:
        return width, height
    for iteration in iterations:
        metadata = _load_metadata(iteration.metadata)
        if isinstance(metadata.get("width"), int) and isinstance(metadata.get("height"), int):
            return int(metadata["width"]), int(metadata["height"])
    return width, height


def _size_attrs(width: int | None, height: int | None) -> str:
    if width and height:
        return f'width="{width}" height="{height}"'
    return ""


def _ruler_overlay(width: int | None, height: int | None) -> str:
    if not width or not height:
        return """<svg class="ruler-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="Macro ruler overlay">
  <rect class="ruler-bg" x="0" y="0" width="100" height="3" />
  <rect class="ruler-bg" x="0" y="0" width="4" height="100" />
  <line class="macro-line" x1="25" y1="0" x2="25" y2="100" />
  <line class="macro-line" x1="50" y1="0" x2="50" y2="100" />
  <line class="macro-line" x1="75" y1="0" x2="75" y2="100" />
  <line class="macro-line" x1="0" y1="12.5" x2="100" y2="12.5" />
  <line class="macro-line" x1="0" y1="25" x2="100" y2="25" />
  <line class="macro-line" x1="0" y1="37.5" x2="100" y2="37.5" />
  <line class="macro-line" x1="0" y1="50" x2="100" y2="50" />
  <line class="macro-line" x1="0" y1="62.5" x2="100" y2="62.5" />
  <line class="macro-line" x1="0" y1="75" x2="100" y2="75" />
  <line class="macro-line" x1="0" y1="87.5" x2="100" y2="87.5" />
</svg>"""
    minor = 8
    major = 40
    parts = [
        f'<svg class="ruler-overlay" viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-label="Pixel ruler overlay">',
        f'<rect class="ruler-bg" x="0" y="0" width="{width}" height="18" />',
        f'<rect class="ruler-bg" x="0" y="0" width="20" height="{height}" />',
    ]
    for x in range(0, width + 1, minor):
        tick_height = 14 if x % major == 0 else 7
        class_name = "tick-major" if x % major == 0 else "tick-minor"
        parts.append(f'<line class="{class_name}" x1="{x}" y1="0" x2="{x}" y2="{tick_height}" />')
        if x and x % major == 0 and x < width:
            parts.append(f'<text class="ruler-label" x="{x + 2}" y="13">{x}</text>')
    for y in range(0, height + 1, minor):
        tick_width = 16 if y % major == 0 else 8
        class_name = "tick-major" if y % major == 0 else "tick-minor"
        parts.append(f'<line class="{class_name}" x1="0" y1="{y}" x2="{tick_width}" y2="{y}" />')
        if y and y % major == 0 and y < height:
            parts.append(f'<text class="ruler-label" x="3" y="{y - 3}">{y}</text>')
    for index in range(5):
        x = round(width * index / 4)
        parts.append(f'<line class="macro-line" x1="{x}" y1="0" x2="{x}" y2="{height}" />')
    for index in range(9):
        y = round(height * index / 8)
        parts.append(f'<line class="macro-line" x1="0" y1="{y}" x2="{width}" y2="{y}" />')
    parts.append("</svg>")
    return "\n".join(parts)


def _ruler_overlay_svg(x_offset: int, y_offset: int, width: int, height: int) -> str:
    minor = 8
    major = 40
    parts = [
        f'<g transform="translate({x_offset} {y_offset})">',
        f'<rect class="ruler-bg" x="0" y="0" width="{width}" height="18" />',
        f'<rect class="ruler-bg" x="0" y="0" width="20" height="{height}" />',
    ]
    for x in range(0, width + 1, minor):
        tick_height = 14 if x % major == 0 else 7
        class_name = "tick-major" if x % major == 0 else "tick-minor"
        parts.append(f'<line class="{class_name}" x1="{x}" y1="0" x2="{x}" y2="{tick_height}" />')
        if x and x % major == 0 and x < width:
            parts.append(f'<text class="ruler-label" x="{x + 2}" y="13">{x}</text>')
    for y in range(0, height + 1, minor):
        tick_width = 16 if y % major == 0 else 8
        class_name = "tick-major" if y % major == 0 else "tick-minor"
        parts.append(f'<line class="{class_name}" x1="0" y1="{y}" x2="{tick_width}" y2="{y}" />')
        if y and y % major == 0 and y < height:
            parts.append(f'<text class="ruler-label" x="3" y="{y - 3}">{y}</text>')
    for index in range(5):
        x = round(width * index / 4)
        parts.append(f'<line class="macro-line" x1="{x}" y1="0" x2="{x}" y2="{height}" />')
    for index in range(9):
        y = round(height * index / 8)
        parts.append(f'<line class="macro-line" x1="0" y1="{y}" x2="{width}" y2="{y}" />')
    parts.append("</g>")
    return "\n".join(parts)


def _mask_script() -> str:
    return r"""
(() => {
  const DIFF_THRESHOLD = 28;
  const EDGE_THRESHOLD = 32;
  for (const review of document.querySelectorAll("[data-agent-review='true']")) {
    analyze(review).catch((error) => {
      review.dataset.maskError = error.message;
    });
  }

  async function analyze(root) {
    const targetImage = await loadImage(root.dataset.targetSrc);
    const currentImage = await loadImage(root.dataset.currentSrc);
    const width = Number(root.dataset.width) || targetImage.naturalWidth || currentImage.naturalWidth;
    const height = Number(root.dataset.height) || targetImage.naturalHeight || currentImage.naturalHeight;
    if (!width || !height) {
      return;
    }
    const targetCanvas = makeCanvas(width, height);
    const currentCanvas = makeCanvas(width, height);
    drawImage(targetCanvas, targetImage, width, height);
    drawImage(currentCanvas, currentImage, width, height);
    const targetData = readPixels(targetCanvas, width, height);
    const currentData = readPixels(currentCanvas, width, height);
    const threshold = thresholdMask(targetData, currentData, width, height);
    const edge = edgeMask(targetData, currentData, width, height);
    const overlay = overlayImage(threshold, edge, width, height);
    for (const canvas of root.querySelectorAll(".mask-canvas")) {
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d").putImageData(overlay, 0, 0);
    }
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error(`could not load ${src}`));
      image.src = src;
    });
  }

  function makeCanvas(width, height) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    return canvas;
  }

  function drawImage(canvas, image, width, height) {
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(image, 0, 0, width, height);
  }

  function readPixels(canvas, width, height) {
    return canvas.getContext("2d", { willReadFrequently: true }).getImageData(0, 0, width, height);
  }

  function thresholdMask(targetData, currentData, width, height) {
    const mask = new Uint8Array(width * height);
    for (let pixel = 0; pixel < mask.length; pixel += 1) {
      const i = pixel * 4;
      const delta = Math.max(
        Math.abs(targetData.data[i] - currentData.data[i]),
        Math.abs(targetData.data[i + 1] - currentData.data[i + 1]),
        Math.abs(targetData.data[i + 2] - currentData.data[i + 2]),
        Math.abs(targetData.data[i + 3] - currentData.data[i + 3]),
      );
      if (delta >= DIFF_THRESHOLD) mask[pixel] = 1;
    }
    return mask;
  }

  function edgeMask(targetData, currentData, width, height) {
    const targetEdges = sobelEdges(targetData, width, height);
    const currentEdges = sobelEdges(currentData, width, height);
    const mask = new Uint8Array(width * height);
    for (let pixel = 0; pixel < mask.length; pixel += 1) {
      if (Math.abs(targetEdges[pixel] - currentEdges[pixel]) > EDGE_THRESHOLD) mask[pixel] = 1;
    }
    return mask;
  }

  function overlayImage(threshold, edge, width, height) {
    const image = new ImageData(width, height);
    for (let pixel = 0; pixel < width * height; pixel += 1) {
      const i = pixel * 4;
      if (threshold[pixel] && edge[pixel]) {
        image.data[i] = 255; image.data[i + 1] = 128; image.data[i + 2] = 0; image.data[i + 3] = 190;
      } else if (threshold[pixel]) {
        image.data[i] = 255; image.data[i + 1] = 42; image.data[i + 2] = 42; image.data[i + 3] = 175;
      } else if (edge[pixel]) {
        image.data[i] = 250; image.data[i + 1] = 204; image.data[i + 2] = 21; image.data[i + 3] = 185;
      }
    }
    return image;
  }

  function grayscaleArray(imageData, width, height) {
    const gray = new Uint8ClampedArray(width * height);
    for (let pixel = 0; pixel < gray.length; pixel += 1) {
      const i = pixel * 4;
      gray[pixel] = Math.round(imageData.data[i] * 0.299 + imageData.data[i + 1] * 0.587 + imageData.data[i + 2] * 0.114);
    }
    return gray;
  }

  function sobelEdges(imageData, width, height) {
    const gray = grayscaleArray(imageData, width, height);
    const edges = new Uint8ClampedArray(width * height);
    for (let y = 1; y < height - 1; y += 1) {
      for (let x = 1; x < width - 1; x += 1) {
        const index = y * width + x;
        const tl = gray[index - width - 1], t = gray[index - width], tr = gray[index - width + 1];
        const l = gray[index - 1], r = gray[index + 1];
        const bl = gray[index + width - 1], b = gray[index + width], br = gray[index + width + 1];
        const gx = -tl + tr - 2 * l + 2 * r - bl + br;
        const gy = -tl - 2 * t - tr + bl + 2 * b + br;
        edges[index] = Math.min(255, Math.abs(gx) + Math.abs(gy));
      }
    }
    return edges;
  }
})();
""".strip()


def _score_record(
    metadata: dict[str, Any],
    *,
    target: Path | None = None,
    actual: Path | None = None,
    attestation_key_env: str = DEFAULT_ATTESTATION_KEY_ENV,
) -> ScoreRecord | None:
    score = metadata.get("score") if isinstance(metadata, dict) else None
    if not isinstance(score, dict):
        return None
    value = _score_value(score)
    if value is None:
        return None
    verified = _score_fields_verified(score)
    if target is not None and actual is not None:
        verified = verified and _input_hashes_match(metadata, target=target, actual=actual)
    attested = _attestation_verified(metadata, key_env=attestation_key_env)
    return ScoreRecord(overall=value, verified=verified, attested=attested)


def _score_value(score: dict[str, Any]) -> float | None:
    try:
        return float(score["overall"])
    except (KeyError, TypeError, ValueError):
        return None


def _score_fields_verified(score: dict[str, Any]) -> bool:
    if score.get("source") != "opencv_diff_boxes":
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
    return float(score["total_pixels"]) > 0


def _input_hashes_match(metadata: dict[str, Any], *, target: Path, actual: Path) -> bool:
    inputs = metadata.get("inputs") if isinstance(metadata, dict) else None
    if not isinstance(inputs, dict):
        return False
    target_hash = inputs.get("target_sha256")
    actual_hash = inputs.get("actual_sha256")
    if not isinstance(target_hash, str) or not isinstance(actual_hash, str):
        return False
    try:
        return target_hash == _sha256(target) and actual_hash == _sha256(actual)
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _attach_attestation(metadata: dict[str, Any], *, key: str, key_id: str = "default") -> None:
    metadata["attestation"] = {
        "type": ATTESTATION_TYPE,
        "version": ATTESTATION_VERSION,
        "key_id": key_id,
        "signed_fields": list(ATTESTATION_SIGNED_FIELDS),
        "signature": _attestation_signature(metadata, key),
    }


def _attestation_verified(metadata: dict[str, Any], *, key_env: str) -> bool:
    key = os.environ.get(key_env)
    if not key:
        return False
    attestation = metadata.get("attestation") if isinstance(metadata, dict) else None
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
    expected = _attestation_signature(metadata, key)
    return hmac.compare_digest(signature, expected)


def _attestation_signature(metadata: dict[str, Any], key: str) -> str:
    canonical = json.dumps(
        _attestation_payload(metadata),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _attestation_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    return {field: metadata.get(field) for field in ATTESTATION_SIGNED_FIELDS}


def _require_verified_scores(
    target: Path,
    iterations: list[GoalIteration],
    *,
    require_attestation: bool = False,
    attestation_key_env: str = DEFAULT_ATTESTATION_KEY_ENV,
) -> None:
    if require_attestation and not os.environ.get(attestation_key_env):
        raise SystemExit(f"missing attestation key: set {attestation_key_env}")
    for iteration in iterations:
        if iteration.metadata is None:
            raise SystemExit(f"unverified score metadata: missing metadata for iteration {iteration.index}")
        metadata = _load_metadata(iteration.metadata)
        record = _score_record(
            metadata,
            target=target,
            actual=iteration.screenshot,
            attestation_key_env=attestation_key_env,
        )
        if record is None or not record.verified:
            raise SystemExit(f"unverified score metadata: {iteration.metadata}")
        if require_attestation and not record.attested:
            raise SystemExit(f"untrusted score attestation: {iteration.metadata}")


def _state_score(score: ScoreRecord | None) -> str:
    if score is None:
        return "n/a"
    suffix = "" if score.verified else " (unverified)"
    return f"{score.overall:.6f}{suffix}"


def _iteration_label(iteration: GoalIteration | None) -> str:
    return "n/a" if iteration is None else str(iteration.index)


def _bullet_lines(values: list[str], *, empty: str) -> list[str]:
    if not values:
        return [f"- {empty}"]
    return [f"- {value}" for value in values]


if __name__ == "__main__":
    raise SystemExit(main())
