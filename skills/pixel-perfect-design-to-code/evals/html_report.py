"""Generate an HTML side-by-side report for inline Codex eval cases."""

from __future__ import annotations

import base64
import os
import json
import re
from html import escape
from pathlib import Path

from mobile_grid_overlay.evals import (
    EvalCase,
    answer_text_for_grading,
    build_prompt,
    grade_answer,
    public_actual_path,
    public_case_label,
    public_clean_actual_path,
    public_clean_mock_path,
    public_mock_path,
)


ROOT = Path(__file__).resolve().parents[3]
EVALS_ROOT = Path(__file__).resolve().parent


def render_side_by_side_html(
    cases: list[EvalCase] | tuple[EvalCase, ...],
    template: str,
    *,
    report_path: Path,
    answers: dict[str, object] | None = None,
    transcripts_dir: Path | None = None,
) -> str:
    answer_map = answers or {}
    sections = "\n".join(
        _render_case(case, template, report_path, answer_map.get(case.id), transcripts_dir)
        for case in cases
    )
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>Grid Screenshot Evals</title>",
            "<style>",
            _style(),
            "</style>",
            "</head>",
            "<body>",
            "<main>",
            "<h1>Grid Screenshot Evals</h1>",
            (
                "<p class=\"lede\">Each case shows the exact inline Codex prompt plus "
                "target design and implementation screenshots with the same grid overlay.</p>"
            ),
            sections,
            "</main>",
            "<script>",
            _script(),
            "</script>",
            "</body>",
            "</html>",
            "",
        ]
    )


def write_side_by_side_html(
    cases: list[EvalCase] | tuple[EvalCase, ...],
    template: str,
    out_path: Path,
    answers: dict[str, object] | None = None,
    transcripts_dir: Path | None = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = render_side_by_side_html(
        cases,
        template,
        report_path=out_path,
        answers=answers,
        transcripts_dir=transcripts_dir,
    )
    out_path.write_text(html, encoding="utf-8")


def _render_case(
    case: EvalCase,
    template: str,
    report_path: Path,
    answer: object | None,
    transcripts_dir: Path | None,
) -> str:
    prompt = build_prompt(case, template)
    case_label = public_case_label(case.id)
    mock_src = _relative_to_report(public_mock_path(case), report_path)
    actual_src = _relative_to_report(public_actual_path(case), report_path)
    clean_mock_src = _relative_to_report(public_clean_mock_path(case), report_path)
    clean_actual_src = _relative_to_report(public_clean_actual_path(case), report_path)
    clean_mock_pixel_src = _image_data_uri(public_clean_mock_path(case))
    clean_actual_pixel_src = _image_data_uri(public_clean_actual_path(case))
    size = f"{case.width}x{case.height}"
    return "\n".join(
        [
            '<section class="case">',
            "<header>",
            f"<h2>{escape(case_label)}</h2>",
            f"<p>{escape(case.platform)} · {escape(case.profile)} · {escape(size)}</p>",
            "</header>",
            '<div class="screens">',
            _figure(
                "Target design",
                mock_src,
                case,
                case_label,
                markers=_target_markers(case),
                overlay_class="target-mask-overlay",
            ),
            _figure(
                "After: implementation",
                actual_src,
                case,
                case_label,
                markers=_cell_markers(case, answer),
                overlay_class="actual-mask-overlay",
            ),
            "</div>",
            '<div class="diffs">',
            _diff_figure(
                "Strict diff mask (no grid)",
                clean_mock_src,
                clean_actual_src,
                case,
                case_label,
            ),
            "</div>",
            _review_layers(
                case,
                case_label,
                clean_mock_src,
                clean_actual_src,
                clean_mock_pixel_src,
                clean_actual_pixel_src,
                report_path,
            ),
            "<h3>Inline Codex Prompt</h3>",
            f"<pre>{escape(prompt)}</pre>",
            _agent_dialogs(case, report_path, transcripts_dir),
            _agent_output(case, answer),
            "</section>",
        ]
    )


def _diff_figure(
    label: str,
    mock_src: str,
    actual_src: str,
    case: EvalCase,
    case_label: str,
) -> str:
    return "\n".join(
        [
            '<figure class="diff-figure">',
            f"<figcaption>{escape(label)}</figcaption>",
            '<div class="diff-frame">',
            (
                f'<img class="diff-base" src="{escape(mock_src, quote=True)}" '
                f'width="{case.width}" height="{case.height}" '
                f'alt="Clean target design for {escape(case_label)}">'
            ),
            (
                f'<img class="diff-top" src="{escape(actual_src, quote=True)}" '
                f'width="{case.width}" height="{case.height}" '
                f'alt="Clean implementation difference layer for {escape(case_label)}">'
            ),
            "</div>",
            "</figure>",
        ]
    )


def _review_layers(
    case: EvalCase,
    case_label: str,
    clean_mock_src: str,
    clean_actual_src: str,
    clean_mock_pixel_src: str,
    clean_actual_pixel_src: str,
    report_path: Path,
) -> str:
    artifact_layers = _artifact_review_layers(case_label, report_path)
    return "\n".join(
        [
            (
                f'<section class="review-layers" data-diff-review="true" '
                f'data-case="{escape(case_label, quote=True)}" '
                f'data-platform="{escape(case.platform, quote=True)}" '
                f'data-width="{case.width}" data-height="{case.height}" '
                f'data-mock-src="{escape(clean_mock_src, quote=True)}" '
                f'data-actual-src="{escape(clean_actual_src, quote=True)}" '
                f'data-mock-pixel-src="{escape(clean_mock_pixel_src, quote=True)}" '
                f'data-actual-pixel-src="{escape(clean_actual_pixel_src, quote=True)}">'
            ),
            "<h3>Visual Review Layers</h3>",
            '<div class="review-grid">',
            _canvas_figure("Threshold diff mask", "threshold-canvas", case),
            _canvas_figure("Diff boxes (M1, M2...)", "boxed-canvas", case, boxed=True),
            _canvas_figure("Edge/shape diff", "edge-canvas", case),
            _canvas_figure("Structural heatmap", "structure-canvas", case),
            _region_mode_figure(case, case_label, clean_actual_src),
            "</div>",
            '<div class="zoom-section">',
            "<h4>Zoom crops</h4>",
            '<div class="zoom-cards" aria-live="polite"></div>',
            '<pre class="mask-metadata">Waiting for browser-side mask analysis...</pre>',
            "</div>",
            "</section>",
            artifact_layers,
        ]
    )


def _artifact_review_layers(case_label: str, report_path: Path) -> str:
    artifact_dir = EVALS_ROOT / "review_artifacts" / case_label
    review_panel = artifact_dir / f"{case_label}_review_panel.png"
    if not review_panel.exists():
        return ""
    layer_specs = (
        ("Review panel", f"{case_label}_review_panel.png"),
        ("Side by side + boxes", f"{case_label}_side_by_side.png"),
        ("Threshold diff mask", f"{case_label}_threshold.png"),
        ("Diff boxes (M1, M2...)", f"{case_label}_boxes.png"),
        ("Edge/shape diff", f"{case_label}_edge.png"),
        ("Structural heatmap", f"{case_label}_structural_heatmap.png"),
        ("Region mode overlay", f"{case_label}_regions.png"),
        ("Strict diff", f"{case_label}_strict_diff.png"),
        ("Combined mask", f"{case_label}_combined.png"),
    )
    figures = []
    for label, filename in layer_specs:
        path = artifact_dir / filename
        if path.exists():
            figures.append(_static_layer_figure(label, path, report_path))
    zooms = [
        _static_layer_figure(path.stem.removeprefix(f"{case_label}_"), path, report_path)
        for path in sorted(artifact_dir.glob(f"{case_label}_M*_zoom.png"))
    ]
    zoom_section = ""
    if zooms:
        zoom_section = "\n".join(
            [
                '<div class="zoom-section">',
                "<h4>Zoom crops</h4>",
                '<div class="zoom-cards static-zoom-cards">',
                *zooms,
                "</div>",
                "</div>",
            ]
        )
    return "\n".join(
        [
            '<section class="review-layers artifact-review-layers">',
            "<h3>Generated artifact images</h3>",
            '<div class="review-grid">',
            *figures,
            "</div>",
            zoom_section,
            "</section>",
        ]
    )


def _static_layer_figure(label: str, path: Path, report_path: Path) -> str:
    src = Path(os.path.relpath(path, start=report_path.parent)).as_posix()
    return "\n".join(
        [
            '<figure class="review-layer static-review-layer">',
            f"<figcaption>{escape(label)}</figcaption>",
            (
                f'<img src="{escape(src, quote=True)}" '
                f'alt="{escape(label, quote=True)}">'
            ),
            "</figure>",
        ]
    )


def _canvas_figure(label: str, canvas_class: str, case: EvalCase, *, boxed: bool = False) -> str:
    canvas = (
        f'<canvas class="{canvas_class}" width="{case.width}" height="{case.height}" '
        f'aria-label="{escape(label, quote=True)}"></canvas>'
    )
    if boxed:
        canvas = "\n".join(
            [
                '<div class="canvas-frame">',
                canvas,
                '<div class="box-dom-layer" aria-label="Detected diff boxes"></div>',
                "</div>",
            ]
        )
    return "\n".join(
        [
            '<figure class="review-layer">',
            f"<figcaption>{escape(label)}</figcaption>",
            canvas,
            "</figure>",
        ]
    )


def _region_mode_figure(case: EvalCase, case_label: str, clean_actual_src: str) -> str:
    top, bottom = _safe_area_bands(case)
    strict_height = max(0, case.height - top - bottom)
    return "\n".join(
        [
            '<figure class="review-layer region-layer">',
            "<figcaption>Region mode overlay</figcaption>",
            '<div class="image-frame">',
            (
                f'<img src="{escape(clean_actual_src, quote=True)}" '
                f'width="{case.width}" height="{case.height}" '
                f'alt="Region mode overlay for {escape(case_label)}">'
            ),
            (
                f'<svg class="region-mode-layer" viewBox="0 0 {case.width} {case.height}" '
                'preserveAspectRatio="none">'
            ),
            (
                f'<rect class="region-band ignore" data-region-mode="ignore" '
                f'x="0" y="0" width="{case.width}" height="{top}" />'
            ),
            (
                f'<rect class="region-band strict" data-region-mode="strict" '
                f'x="0" y="{top}" width="{case.width}" height="{strict_height}" />'
            ),
            (
                f'<rect class="region-band ignore" data-region-mode="ignore" '
                f'x="0" y="{case.height - bottom}" width="{case.width}" height="{bottom}" />'
            ),
            "</svg>",
            "</div>",
            "</figure>",
        ]
    )


def _safe_area_bands(case: EvalCase) -> tuple[int, int]:
    if case.platform == "ios" or case.profile == "ios":
        return 47, 34
    if case.platform == "android" or case.profile == "android":
        return 24, 48
    return 0, 0


def _agent_output(case: EvalCase, answer: object | None) -> str:
    if answer is None:
        return ""
    result = grade_answer(case, answer)
    status = "PASS" if result.passed else "FAIL"
    details = f"{status} · score={result.score:.3f}"
    if result.missed_findings:
        details += f" · missed: {', '.join(result.missed_findings)}"
    if result.false_alarms:
        details += f" · false alarms: {', '.join(result.false_alarms)}"
    return "\n".join(
        [
            "<h3>Agent Output</h3>",
            f'<p class="grade {status.lower()}">{escape(details)}</p>',
            f"<pre>{escape(_format_answer(answer))}</pre>",
        ]
    )


def _agent_dialogs(case: EvalCase, report_path: Path, transcripts_dir: Path | None) -> str:
    if transcripts_dir is None:
        return ""
    dialogs = []
    for mode in ("with_skill", "without_skill"):
        transcript_path = transcripts_dir / f"{case.id}_{mode}_last_message.json"
        if transcript_path.exists():
            dialogs.append(_agent_dialog(mode, transcript_path, report_path))
    if not dialogs:
        return ""
    return "\n".join(
        [
            '<section class="agent-dialogs">',
            "<h3>Live Agent Dialog</h3>",
            *dialogs,
            "</section>",
        ]
    )


def _agent_dialog(mode: str, transcript_path: Path, report_path: Path) -> str:
    try:
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return "\n".join(
            [
                '<article class="agent-dialog">',
                f"<h4>{escape(mode)}</h4>",
                f"<pre>Could not read transcript: {escape(str(exc))}</pre>",
                "</article>",
            ]
        )

    command = transcript.get("command") if isinstance(transcript, dict) else None
    prompt = transcript.get("prompt") if isinstance(transcript, dict) else ""
    output = transcript.get("output_raw") if isinstance(transcript, dict) else ""
    duration = transcript.get("duration_ms") if isinstance(transcript, dict) else None
    images = _command_images(command)
    image_gallery = "\n".join(
        _dialog_image(index, image_path, report_path) for index, image_path in enumerate(images, start=1)
    )
    command_text = " ".join(str(part) for part in command) if isinstance(command, list) else ""
    duration_text = f"{float(duration):.1f} ms" if isinstance(duration, int | float) else "unknown"
    return "\n".join(
        [
            '<article class="agent-dialog">',
            f"<h4>{escape(mode.replace('_', ' '))}</h4>",
            f'<p class="dialog-meta">Duration: {escape(duration_text)} · Images: {len(images)}</p>',
            '<div class="dialog-images">',
            image_gallery,
            "</div>",
            "<h5>Prompt Sent To Agent</h5>",
            f"<pre>{escape(str(prompt))}</pre>",
            "<h5>Agent Answer</h5>",
            f"<pre>{escape(str(output))}</pre>",
            "<details>",
            "<summary>Command</summary>",
            f"<pre>{escape(command_text)}</pre>",
            "</details>",
            "</article>",
        ]
    )


def _command_images(command: object) -> tuple[str, ...]:
    if not isinstance(command, list):
        return ()
    images: list[str] = []
    for index, part in enumerate(command):
        if part == "--image" and index + 1 < len(command):
            images.append(str(command[index + 1]))
    return tuple(images)


def _dialog_image(index: int, image_path: str, report_path: Path) -> str:
    source = Path(image_path)
    if not source.is_absolute():
        source = ROOT / source
    try:
        src = Path(os.path.relpath(source, start=report_path.parent)).as_posix()
    except ValueError:
        src = source.as_posix()
    label = source.name
    return "\n".join(
        [
            '<figure class="dialog-image">',
            (
                f'<img src="{escape(src, quote=True)}" '
                f'alt="{escape(label, quote=True)}">'
            ),
            f"<figcaption>{index}. {escape(label)}</figcaption>",
            "</figure>",
        ]
    )


def _figure(
    label: str,
    src: str,
    case: EvalCase,
    case_label: str,
    *,
    markers: str,
    overlay_class: str,
) -> str:
    return "\n".join(
        [
            "<figure>",
            f"<figcaption>{escape(label)}</figcaption>",
            '<div class="image-frame">',
            (
                f'<img src="{escape(src, quote=True)}" '
                f'width="{case.width}" height="{case.height}" '
                f'alt="{escape(label)} for {escape(case_label)}">'
            ),
            (
                f'<canvas class="screenshot-mask-overlay {overlay_class}" '
                f'width="{case.width}" height="{case.height}" '
                f'aria-label="{escape(label, quote=True)} diff mask overlay"></canvas>'
            ),
            '<span class="screenshot-mask-legend">Mask overlay: red=color, yellow=edge/shape</span>',
            markers,
            "</div>",
            "</figure>",
        ]
    )


def _cell_markers(case: EvalCase, answer: object | None) -> str:
    expected = _expected_cells(case)
    answer_text = answer_text_for_grading(answer or {})
    agent = _answer_cells(answer_text)
    if not expected and not agent:
        return ""

    parts = [
        '<div class="marker-layer" aria-label="Cell Markers">',
        _exclusion_mask(case),
        '<span class="marker-legend">Cell Markers: green expected, red agent</span>',
    ]
    for cell in expected:
        parts.append(_cell_box("expected", cell))
    for cell in agent:
        parts.append(_cell_box("agent", cell))
    for point in _expected_target_points(case):
        parts.append(_target_point("expected", "expected", point[0], point[1], case))
    for point in _answer_points(answer_text):
        parts.append(_target_point("agent", "agent", point[0], point[1], case))
    parts.append("</div>")
    return "\n".join(parts)


def _format_answer(answer: object) -> str:
    if isinstance(answer, str):
        return answer
    return json.dumps(answer, indent=2, ensure_ascii=False)


def _target_markers(case: EvalCase) -> str:
    expected = _expected_cells(case)
    targets = _expected_target_points(case)
    if not expected and not targets:
        return ""
    parts = [
        '<div class="marker-layer" aria-label="Cell Markers">',
        _exclusion_mask(case),
        '<span class="marker-legend">Target: expected cells and points</span>',
    ]
    for cell in expected:
        parts.append(_cell_box("expected", cell))
    for point in targets:
        parts.append(_target_point("expected", "expected", point[0], point[1], case))
    parts.append("</div>")
    return "\n".join(parts)


def _exclusion_mask(case: EvalCase) -> str:
    holes = "\n".join(_mask_hole(cell) for cell in _expected_cells(case))
    mask_id = f"mask-open-cells-{public_case_label(case.id)}"
    return "\n".join(
        [
            '<svg class="exclusion-mask" viewBox="0 0 100 100" preserveAspectRatio="none">',
            "<defs>",
            f'<mask id="{mask_id}">',
            '<rect class="mask-white" x="0" y="0" width="100" height="100" />',
            holes,
            "</mask>",
            "</defs>",
            f'<rect class="mask-fill" x="0" y="0" width="100" height="100" mask="url(#{mask_id})" />',
            "</svg>",
        ]
    )


def _mask_hole(cell: str) -> str:
    left, top, width, height = _cell_bounds_percent(cell)
    return (
        f'<rect class="mask-hole" x="{left:.2f}" y="{top:.2f}" '
        f'width="{width:.2f}" height="{height:.2f}" />'
    )


def _cell_box(kind: str, cell: str) -> str:
    left, top, width, height = _cell_bounds_percent(cell)
    return (
        f'<span class="cell-box {kind}" data-marker-kind="{kind}" data-cell="{cell}" '
        f'style="left:{left:.2f}%;top:{top:.2f}%;width:{width:.2f}%;height:{height:.2f}%"></span>'
    )


def _target_point(kind: str, label: str, x: int, y: int, case: EvalCase) -> str:
    left = x * 100 / case.width
    top = y * 100 / case.height
    return (
        f'<span class="target-point {kind}" data-target-kind="{kind}" '
        f'data-label="{escape(label)}" style="left:{left:.2f}%;top:{top:.2f}%"></span>'
    )


def _expected_cells(case: EvalCase) -> tuple[str, ...]:
    cells: list[str] = []
    for finding in case.expected_findings:
        for term in finding.region_terms:
            if re.fullmatch(r"[a-z]\d+", term):
                cells.append(term.upper())
    return tuple(dict.fromkeys(cells))


def _expected_target_points(case: EvalCase) -> tuple[tuple[int, int], ...]:
    points = [finding.target_point for finding in case.expected_findings if finding.target_point]
    return tuple(dict.fromkeys(points))


def _answer_cells(answer: str) -> tuple[str, ...]:
    cells = [match.group(1).upper() for match in re.finditer(r"\b([A-Za-z]\d{1,2})\b", answer)]
    return tuple(dict.fromkeys(cells))


def _answer_points(answer: str) -> tuple[tuple[int, int], ...]:
    points: list[tuple[int, int]] = []
    for match in re.finditer(
        r"\b(?:point|target)\s*[:=]?\s*\"?\(?\s*(\d+)\s*,\s*(\d+)",
        answer,
        re.I,
    ):
        points.append((int(match.group(1)), int(match.group(2))))
    return tuple(dict.fromkeys(points))


def _cell_bounds_percent(cell: str) -> tuple[float, float, float, float]:
    column_count = 4
    row_count = 8
    column = ord(cell[0]) - ord("A")
    row = int(cell[1:]) - 1
    left = column * 100 / column_count
    top = row * 100 / row_count
    width = 100 / column_count
    height = 100 / row_count
    return left, top, width, height


def _relative_to_report(path: str, report_path: Path) -> str:
    source_path = _asset_path(path)
    return Path(os.path.relpath(source_path, start=report_path.parent)).as_posix()


def _image_data_uri(path: str) -> str:
    source_path = _asset_path(path)
    try:
        payload = base64.b64encode(source_path.read_bytes()).decode("ascii")
    except OSError:
        return path
    return f"data:image/png;base64,{payload}"


def _asset_path(path: str) -> Path:
    source_path = Path(path)
    if source_path.is_absolute():
        return source_path
    if source_path.parts and source_path.parts[0] in {"public", "review_artifacts"}:
        return EVALS_ROOT / source_path
    return ROOT / source_path


def _script() -> str:
    return r"""
(() => {
  const DIFF_THRESHOLD = 28;
  const EDGE_THRESHOLD = 32;
  const DILATE_RADIUS = 4;
  const MERGE_GAP = 14;
  const MAX_BOXES = 12;

  const reviews = document.querySelectorAll('[data-diff-review="true"]');
  for (const review of reviews) {
    analyzeReview(review).catch((error) => {
      const metadata = review.querySelector(".mask-metadata");
      if (metadata) {
        metadata.textContent = `Mask analysis failed: ${error.message}`;
      }
    });
  }

  async function analyzeReview(root) {
    const width = Number(root.dataset.width);
    const height = Number(root.dataset.height);
    const mock = await loadImage(root.dataset.mockPixelSrc || root.dataset.mockSrc);
    const actual = await loadImage(root.dataset.actualPixelSrc || root.dataset.actualSrc);
    const targetCanvas = makeCanvas(width, height);
    const actualCanvas = makeCanvas(width, height);
    drawImage(targetCanvas, mock, width, height);
    drawImage(actualCanvas, actual, width, height);

    const targetData = readPixels(targetCanvas, width, height);
    const actualData = readPixels(actualCanvas, width, height);
    const { mask, thresholdImage } = buildThresholdMask(targetData, actualData, width, height);
    const thresholdCanvas = root.querySelector(".threshold-canvas");
    thresholdCanvas.getContext("2d").putImageData(thresholdImage, 0, 0);
    const edgeDiff = buildEdgeDiff(targetData, actualData, width, height);
    root.querySelector(".edge-canvas").getContext("2d").putImageData(edgeDiff.image, 0, 0);
    drawScreenshotMaskOverlays(root, buildScreenshotMaskOverlay(mask, edgeDiff.mask, width, height));
    drawStructureCanvas(root.querySelector(".structure-canvas"), targetData, actualData, width, height);
    const combinedMask = combineMasks(mask, edgeDiff.mask);
    const combinedCanvas = makeCanvas(width, height);
    combinedCanvas.getContext("2d").putImageData(
      combineDiffImages(thresholdImage, edgeDiff.image, width, height),
      0,
      0,
    );

    const dilated = dilateMask(combinedMask, width, height, DILATE_RADIUS);
    const boxes = mergeBoxes(
      connectedBoxes(dilated, width, height)
        .filter((box) => box.area >= 20 && box.width >= 3 && box.height >= 3),
      MERGE_GAP,
    )
      .sort((a, b) => (a.y - b.y) || (a.x - b.x))
      .slice(0, MAX_BOXES)
      .map((box, index) => ({ ...box, id: `M${index + 1}` }));

    drawBoxedCanvas(root.querySelector(".boxed-canvas"), actualCanvas, boxes, width, height);
    drawBoxDomLayer(root.querySelector(".box-dom-layer"), boxes, width, height);
    drawZoomCards(root.querySelector(".zoom-cards"), boxes, targetCanvas, actualCanvas, combinedCanvas, width, height);
    writeMetadata(root.querySelector(".mask-metadata"), boxes, width, height);
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

  function buildThresholdMask(targetData, actualData, width, height) {
    const mask = new Uint8Array(width * height);
    const thresholdImage = new ImageData(width, height);
    const out = thresholdImage.data;
    for (let pixel = 0; pixel < mask.length; pixel += 1) {
      const i = pixel * 4;
      const delta = Math.max(
        Math.abs(targetData.data[i] - actualData.data[i]),
        Math.abs(targetData.data[i + 1] - actualData.data[i + 1]),
        Math.abs(targetData.data[i + 2] - actualData.data[i + 2]),
        Math.abs(targetData.data[i + 3] - actualData.data[i + 3]),
      );
      out[i] = 0;
      out[i + 1] = 0;
      out[i + 2] = 0;
      out[i + 3] = 255;
      if (delta >= DIFF_THRESHOLD) {
        mask[pixel] = 1;
        out[i] = 255;
        out[i + 1] = 42;
        out[i + 2] = 42;
      }
    }
    return { mask, thresholdImage };
  }

  function combineMasks(first, second) {
    const out = new Uint8Array(first.length);
    for (let i = 0; i < first.length; i += 1) {
      out[i] = first[i] || second[i] ? 1 : 0;
    }
    return out;
  }

  function combineDiffImages(thresholdImage, edgeImage, width, height) {
    const image = new ImageData(width, height);
    for (let pixel = 0; pixel < width * height; pixel += 1) {
      const i = pixel * 4;
      image.data[i] = 0;
      image.data[i + 1] = 0;
      image.data[i + 2] = 0;
      image.data[i + 3] = 255;
      if (thresholdImage.data[i] || thresholdImage.data[i + 1] || thresholdImage.data[i + 2]) {
        image.data[i] = thresholdImage.data[i];
        image.data[i + 1] = thresholdImage.data[i + 1];
        image.data[i + 2] = thresholdImage.data[i + 2];
      } else if (edgeImage.data[i] || edgeImage.data[i + 1] || edgeImage.data[i + 2]) {
        image.data[i] = edgeImage.data[i];
        image.data[i + 1] = edgeImage.data[i + 1];
        image.data[i + 2] = edgeImage.data[i + 2];
      }
    }
    return image;
  }

  function buildScreenshotMaskOverlay(thresholdMask, edgeMask, width, height) {
    const image = new ImageData(width, height);
    for (let pixel = 0; pixel < width * height; pixel += 1) {
      const i = pixel * 4;
      const threshold = thresholdMask[pixel];
      const edge = edgeMask[pixel];
      if (threshold && edge) {
        image.data[i] = 255;
        image.data[i + 1] = 128;
        image.data[i + 2] = 0;
        image.data[i + 3] = 190;
      } else if (threshold) {
        image.data[i] = 255;
        image.data[i + 1] = 42;
        image.data[i + 2] = 42;
        image.data[i + 3] = 175;
      } else if (edge) {
        image.data[i] = 250;
        image.data[i + 1] = 204;
        image.data[i + 2] = 21;
        image.data[i + 3] = 185;
      }
    }
    return image;
  }

  function drawScreenshotMaskOverlays(root, overlayImage) {
    const section = root.closest(".case");
    if (!section) {
      return;
    }
    for (const canvas of section.querySelectorAll(".screenshot-mask-overlay")) {
      canvas.getContext("2d").putImageData(overlayImage, 0, 0);
    }
  }

  function dilateMask(mask, width, height, radius) {
    const out = new Uint8Array(mask.length);
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const index = y * width + x;
        if (!mask[index]) {
          continue;
        }
        for (let dy = -radius; dy <= radius; dy += 1) {
          const yy = y + dy;
          if (yy < 0 || yy >= height) {
            continue;
          }
          for (let dx = -radius; dx <= radius; dx += 1) {
            const xx = x + dx;
            if (xx >= 0 && xx < width) {
              out[yy * width + xx] = 1;
            }
          }
        }
      }
    }
    return out;
  }

  function connectedBoxes(mask, width, height) {
    const visited = new Uint8Array(mask.length);
    const boxes = [];
    const neighbors = [-width - 1, -width, -width + 1, -1, 1, width - 1, width, width + 1];
    for (let start = 0; start < mask.length; start += 1) {
      if (!mask[start] || visited[start]) {
        continue;
      }
      const stack = [start];
      visited[start] = 1;
      let minX = width;
      let minY = height;
      let maxX = 0;
      let maxY = 0;
      let area = 0;
      while (stack.length) {
        const index = stack.pop();
        const x = index % width;
        const y = Math.floor(index / width);
        area += 1;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
        for (const offset of neighbors) {
          const next = index + offset;
          if (next < 0 || next >= mask.length || visited[next] || !mask[next]) {
            continue;
          }
          const nx = next % width;
          if (Math.abs(nx - x) > 1) {
            continue;
          }
          visited[next] = 1;
          stack.push(next);
        }
      }
      boxes.push({
        x: minX,
        y: minY,
        width: maxX - minX + 1,
        height: maxY - minY + 1,
        area,
      });
    }
    return boxes;
  }

  function mergeBoxes(inputBoxes, gap) {
    const boxes = inputBoxes.map((box) => ({ ...box }));
    let changed = true;
    while (changed) {
      changed = false;
      for (let i = 0; i < boxes.length; i += 1) {
        for (let j = i + 1; j < boxes.length; j += 1) {
          if (!boxesAreNear(boxes[i], boxes[j], gap)) {
            continue;
          }
          boxes[i] = unionBox(boxes[i], boxes[j]);
          boxes.splice(j, 1);
          changed = true;
          break;
        }
        if (changed) {
          break;
        }
      }
    }
    return boxes;
  }

  function boxesAreNear(a, b, gap) {
    return !(
      a.x + a.width + gap < b.x ||
      b.x + b.width + gap < a.x ||
      a.y + a.height + gap < b.y ||
      b.y + b.height + gap < a.y
    );
  }

  function unionBox(a, b) {
    const x = Math.min(a.x, b.x);
    const y = Math.min(a.y, b.y);
    const right = Math.max(a.x + a.width, b.x + b.width);
    const bottom = Math.max(a.y + a.height, b.y + b.height);
    return {
      x,
      y,
      width: right - x,
      height: bottom - y,
      area: a.area + b.area,
    };
  }

  function drawBoxedCanvas(canvas, actualCanvas, boxes, width, height) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(actualCanvas, 0, 0);
    ctx.lineWidth = 3;
    ctx.font = "700 16px system-ui, sans-serif";
    for (const box of boxes) {
      ctx.strokeStyle = "#ef4444";
      ctx.fillStyle = "rgba(239, 68, 68, .12)";
      ctx.fillRect(box.x, box.y, box.width, box.height);
      ctx.strokeRect(box.x, box.y, box.width, box.height);
      ctx.fillStyle = "#dc2626";
      ctx.fillRect(box.x, Math.max(0, box.y - 21), 34, 20);
      ctx.fillStyle = "#ffffff";
      ctx.fillText(box.id, box.x + 5, Math.max(16, box.y - 6));
    }
  }

  function drawBoxDomLayer(layer, boxes, width, height) {
    layer.replaceChildren();
    for (const box of boxes) {
      const marker = document.createElement("span");
      marker.className = "diff-box";
      marker.dataset.maskId = box.id;
      marker.style.left = `${box.x * 100 / width}%`;
      marker.style.top = `${box.y * 100 / height}%`;
      marker.style.width = `${box.width * 100 / width}%`;
      marker.style.height = `${box.height * 100 / height}%`;
      const label = document.createElement("span");
      label.className = "diff-box-label";
      label.textContent = box.id;
      marker.append(label);
      layer.append(marker);
    }
  }

  function buildEdgeDiff(targetData, actualData, width, height) {
    const targetEdges = sobelEdges(targetData, width, height);
    const actualEdges = sobelEdges(actualData, width, height);
    const image = new ImageData(width, height);
    const mask = new Uint8Array(width * height);
    for (let pixel = 0; pixel < targetEdges.length; pixel += 1) {
      const i = pixel * 4;
      const delta = Math.abs(targetEdges[pixel] - actualEdges[pixel]);
      image.data[i] = 0;
      image.data[i + 1] = 0;
      image.data[i + 2] = 0;
      image.data[i + 3] = 255;
      if (delta > EDGE_THRESHOLD) {
        mask[pixel] = 1;
        image.data[i] = 250;
        image.data[i + 1] = 204;
        image.data[i + 2] = 21;
      }
    }
    return { image, mask };
  }

  function drawStructureCanvas(canvas, targetData, actualData, width, height) {
    const targetGray = grayscaleArray(targetData, width, height);
    const actualGray = grayscaleArray(actualData, width, height);
    const targetIntegral = integralImage(targetGray, width, height);
    const actualIntegral = integralImage(actualGray, width, height);
    const image = new ImageData(width, height);
    const radius = 3;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const pixel = y * width + x;
        const i = pixel * 4;
        const localDelta = Math.abs(
          localMean(targetIntegral, x, y, width, height, radius) -
          localMean(actualIntegral, x, y, width, height, radius)
        );
        const pointDelta = Math.abs(targetGray[pixel] - actualGray[pixel]);
        const score = Math.min(255, localDelta * 8 + pointDelta * 0.75);
        image.data[i] = score;
        image.data[i + 1] = Math.max(0, score - 80);
        image.data[i + 2] = score > 8 ? 255 - Math.min(180, score) : 0;
        image.data[i + 3] = 255;
      }
    }
    canvas.getContext("2d").putImageData(image, 0, 0);
  }

  function grayscaleArray(imageData, width, height) {
    const gray = new Uint8ClampedArray(width * height);
    for (let pixel = 0; pixel < gray.length; pixel += 1) {
      const i = pixel * 4;
      gray[pixel] = Math.round(
        imageData.data[i] * 0.299 +
        imageData.data[i + 1] * 0.587 +
        imageData.data[i + 2] * 0.114
      );
    }
    return gray;
  }

  function integralImage(gray, width, height) {
    const stride = width + 1;
    const integral = new Float64Array((width + 1) * (height + 1));
    for (let y = 1; y <= height; y += 1) {
      let rowSum = 0;
      for (let x = 1; x <= width; x += 1) {
        rowSum += gray[(y - 1) * width + (x - 1)];
        integral[y * stride + x] = integral[(y - 1) * stride + x] + rowSum;
      }
    }
    return integral;
  }

  function localMean(integral, x, y, width, height, radius) {
    const stride = width + 1;
    const x1 = Math.max(0, x - radius);
    const y1 = Math.max(0, y - radius);
    const x2 = Math.min(width - 1, x + radius);
    const y2 = Math.min(height - 1, y + radius);
    const left = x1;
    const top = y1;
    const right = x2 + 1;
    const bottom = y2 + 1;
    const area = (right - left) * (bottom - top);
    const sum =
      integral[bottom * stride + right] -
      integral[top * stride + right] -
      integral[bottom * stride + left] +
      integral[top * stride + left];
    return sum / area;
  }

  function sobelEdges(imageData, width, height) {
    const gray = grayscaleArray(imageData, width, height);
    const edges = new Uint8ClampedArray(width * height);
    for (let y = 1; y < height - 1; y += 1) {
      for (let x = 1; x < width - 1; x += 1) {
        const index = y * width + x;
        const tl = gray[index - width - 1];
        const t = gray[index - width];
        const tr = gray[index - width + 1];
        const l = gray[index - 1];
        const r = gray[index + 1];
        const bl = gray[index + width - 1];
        const b = gray[index + width];
        const br = gray[index + width + 1];
        const gx = -tl + tr - 2 * l + 2 * r - bl + br;
        const gy = -tl - 2 * t - tr + bl + 2 * b + br;
        edges[index] = Math.min(255, Math.abs(gx) + Math.abs(gy));
      }
    }
    return edges;
  }

  function drawZoomCards(container, boxes, targetCanvas, actualCanvas, thresholdCanvas, width, height) {
    container.replaceChildren();
    for (const box of boxes) {
      const crop = paddedCrop(box, width, height, 16);
      const card = document.createElement("article");
      card.className = "zoom-card";
      const title = document.createElement("h5");
      title.textContent = `${box.id} ${cellsForBox(box, width, height).join("/")}`;
      const meta = document.createElement("p");
      meta.textContent = `bbox ${box.x},${box.y},${box.width}x${box.height}; point ${centerPoint(box).join(",")}`;
      const strip = document.createElement("div");
      strip.className = "zoom-strip";
      strip.append(
        cropCanvas(targetCanvas, crop, "target"),
        cropCanvas(actualCanvas, crop, "actual"),
        cropCanvas(thresholdCanvas, crop, "diff"),
      );
      card.append(title, meta, strip);
      container.append(card);
    }
  }

  function cropCanvas(sourceCanvas, crop, label) {
    const canvas = makeCanvas(crop.width, crop.height);
    canvas.className = `zoom-canvas zoom-${label}`;
    canvas.title = label;
    canvas.getContext("2d").drawImage(
      sourceCanvas,
      crop.x,
      crop.y,
      crop.width,
      crop.height,
      0,
      0,
      crop.width,
      crop.height,
    );
    return canvas;
  }

  function paddedCrop(box, width, height, padding) {
    const x = Math.max(0, box.x - padding);
    const y = Math.max(0, box.y - padding);
    const right = Math.min(width, box.x + box.width + padding);
    const bottom = Math.min(height, box.y + box.height + padding);
    return { x, y, width: right - x, height: bottom - y };
  }

  function writeMetadata(metadata, boxes, width, height) {
    const payload = boxes.map((box) => ({
      mask_id: box.id,
      bbox: [box.x, box.y, box.width, box.height],
      point: centerPoint(box),
      cells: cellsForBox(box, width, height),
    }));
    metadata.textContent = payload.length
      ? JSON.stringify(payload, null, 2)
      : "No thresholded differences found.";
  }

  function centerPoint(box) {
    return [
      Math.round(box.x + box.width / 2),
      Math.round(box.y + box.height / 2),
    ];
  }

  function cellsForBox(box, width, height) {
    const columns = "ABCD";
    const cellWidth = width / 4;
    const cellHeight = height / 8;
    const left = clamp(Math.floor(box.x / cellWidth), 0, 3);
    const right = clamp(Math.floor((box.x + box.width - 1) / cellWidth), 0, 3);
    const top = clamp(Math.floor(box.y / cellHeight), 0, 7);
    const bottom = clamp(Math.floor((box.y + box.height - 1) / cellHeight), 0, 7);
    const cells = [];
    for (let row = top; row <= bottom; row += 1) {
      for (let column = left; column <= right; column += 1) {
        cells.push(`${columns[column]}${row + 1}`);
      }
    }
    return cells;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }
})();
""".strip()


def _style() -> str:
    return """
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #121826;
  background: #f4f6f8;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

main {
  width: min(1440px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 32px 0 48px;
}

h1,
h2,
h3,
p {
  margin: 0;
}

h1 {
  font-size: 32px;
  line-height: 1.15;
}

.lede {
  margin-top: 8px;
  color: #4b5563;
  font-size: 15px;
}

.case {
  margin-top: 28px;
  padding: 20px;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #ffffff;
}

.case header {
  display: grid;
  gap: 6px;
}

.case header p {
  color: #4b5563;
  font-size: 14px;
}

h2 {
  font-size: 22px;
  line-height: 1.2;
}

h3 {
  margin-top: 18px;
  font-size: 15px;
}

.screens {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
  margin-top: 16px;
}

.diffs {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  margin-top: 16px;
}

.review-layers {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid #d8dee8;
}

.review-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-top: 12px;
  align-items: start;
}

.zoom-section {
  margin-top: 14px;
}

.zoom-section h4 {
  margin: 0 0 8px;
  font-size: 13px;
}

.zoom-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.zoom-card {
  min-width: 0;
  padding: 10px;
  border: 1px solid #d8dee8;
  border-radius: 6px;
  background: #f8fafc;
}

.zoom-card h5 {
  margin: 0 0 6px;
  font-size: 12px;
}

.zoom-card p {
  margin: 0 0 8px;
  color: #4b5563;
  font-size: 11px;
}

.agent-dialogs {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid #d8dee8;
}

.agent-dialog {
  margin-top: 12px;
  padding: 14px;
  border: 1px solid #d8dee8;
  border-radius: 6px;
  background: #f8fafc;
}

.agent-dialog h4,
.agent-dialog h5 {
  margin: 0;
}

.agent-dialog h4 {
  font-size: 14px;
}

.agent-dialog h5 {
  margin-top: 12px;
  font-size: 12px;
  color: #374151;
}

.dialog-meta {
  margin-top: 4px;
  color: #4b5563;
  font-size: 12px;
}

.dialog-images {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.dialog-image img {
  max-height: 240px;
}

.dialog-image figcaption {
  min-height: 34px;
  font-size: 11px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.zoom-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

figure {
  margin: 0;
  min-width: 0;
}

figcaption {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

img,
canvas {
  display: block;
  width: 100%;
  height: auto;
  max-height: 78vh;
  object-fit: contain;
  border: 1px solid #cfd7e3;
  background: #f8fafc;
}

.image-frame {
  position: relative;
  width: fit-content;
  max-width: 100%;
}

.screenshot-mask-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: 0;
  background: transparent;
  pointer-events: none;
  mix-blend-mode: multiply;
  opacity: .76;
}

.screenshot-mask-legend {
  position: absolute;
  left: 8px;
  bottom: 8px;
  padding: 3px 6px;
  border-radius: 4px;
  background: rgba(15, 23, 42, .78);
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  pointer-events: none;
}

.canvas-frame {
  position: relative;
  width: fit-content;
  max-width: 100%;
}

.box-dom-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.diff-box {
  position: absolute;
  border: 2px solid rgba(239, 68, 68, .98);
  background: rgba(239, 68, 68, .10);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, .82);
}

.diff-box-label {
  position: absolute;
  left: -2px;
  top: -20px;
  padding: 2px 5px;
  border-radius: 4px;
  background: #dc2626;
  color: #ffffff;
  font-size: 11px;
  font-weight: 800;
}

.diff-frame {
  position: relative;
  width: fit-content;
  max-width: 100%;
  background: #000000;
  filter: contrast(4) saturate(2);
}

.diff-frame img {
  border: 0;
  background: transparent;
}

.diff-base {
  mix-blend-mode: normal;
}

.diff-top {
  position: absolute;
  inset: 0;
  mix-blend-mode: difference;
}

.region-mode-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.region-band {
  vector-effect: non-scaling-stroke;
}

.region-band.ignore {
  fill: rgba(15, 23, 42, .18);
  stroke: rgba(15, 23, 42, .45);
  stroke-width: 1;
}

.region-band.strict {
  fill: rgba(34, 197, 94, .08);
  stroke: rgba(34, 197, 94, .85);
  stroke-width: 2;
}

.marker-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.exclusion-mask {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.mask-white {
  fill: #ffffff;
}

.mask-hole {
  fill: #000000;
}

.mask-fill {
  fill: rgba(15, 23, 42, .18);
}

.marker-legend {
  position: absolute;
  right: 8px;
  bottom: 8px;
  padding: 3px 6px;
  border-radius: 4px;
  background: rgba(15, 23, 42, .78);
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
}

.cell-box {
  position: absolute;
}

.cell-box.expected {
  border: 2px solid rgba(34, 197, 94, .95);
  background: rgba(34, 197, 94, .12);
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, .65);
}

.cell-box.agent {
  border: 2px dashed rgba(239, 68, 68, .96);
  background: rgba(239, 68, 68, .12);
}

.target-point {
  position: absolute;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, .95);
}

.target-point.expected {
  border: 3px solid #22c55e;
  background: rgba(34, 197, 94, .2);
  color: #22c55e;
}

.target-point.agent {
  border: 3px solid #ef4444;
  background: rgba(239, 68, 68, .24);
  color: #ef4444;
}

.target-point::before,
.target-point::after {
  content: "";
  position: absolute;
  background: currentColor;
}

.target-point::before {
  left: 50%;
  top: -8px;
  width: 2px;
  height: 30px;
  transform: translateX(-50%);
}

.target-point::after {
  left: -8px;
  top: 50%;
  width: 30px;
  height: 2px;
  transform: translateY(-50%);
}

pre {
  margin: 8px 0 0;
  padding: 14px;
  overflow: auto;
  border: 1px solid #d8dee8;
  border-radius: 6px;
  background: #0f172a;
  color: #e5edf8;
  font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  white-space: pre-wrap;
}

.grade {
  margin-top: 8px;
  font-size: 13px;
  font-weight: 700;
}

.grade.pass {
  color: #047857;
}

.grade.fail {
  color: #b91c1c;
}

@media (max-width: 820px) {
  main {
    width: min(100vw - 20px, 720px);
    padding-top: 20px;
  }

  .case {
    padding: 14px;
  }

  .screens {
    grid-template-columns: 1fr;
  }

  .review-grid {
    grid-template-columns: 1fr;
  }
}
""".strip()
