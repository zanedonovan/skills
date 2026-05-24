# Review Layers

Use these layers as independent evidence. Do not replace one layer with another.

## Side-By-Side

Show `Target design` and `After: implementation` first. These are the canonical screenshots the model should compare.

## Grid

Use macro cells `A1...D8` for stable text localization. Use measurement lines and edge rulers to estimate pixel deltas.

## Strict Diff

Use clean no-grid images and `difference` blending. Black means identical; colored pixels indicate RGB differences. This is sensitive to color and anti-aliasing.

For PNG/JPG inputs, `scripts/opencv_diff_boxes.py` writes this as `*_strict_diff.png`.

## Threshold Mask

Use a hard threshold over RGB/alpha differences. This is best for color tokens, fills, missing elements, opacity, and background changes. It can miss same-color shape differences.

For PNG/JPG inputs, use both `*_threshold.png` for the black-background evidence mask and `*_threshold_overlay.png` when the agent needs the mask drawn over the actual screenshot.

## Edge/Shape Diff

Use grayscale edges or Canny/Sobel edges. This is better for radius, glyph shape, icons, alignment, and small text shifts. It is less dependent on color than threshold masks.

For PNG/JPG inputs, use both `*_edge.png` and `*_edge_overlay.png`.

## Structural Heatmap

Use a local grayscale/structure comparison to reveal shape and layout changes. It can miss a pure color swap when brightness stays similar.

For PNG/JPG inputs, `scripts/opencv_diff_boxes.py` writes this as `*_structural_heatmap.png`.

## Boxes And Crops

Build `M1`, `M2`, ... boxes from combined threshold+edge masks. For every box, provide:

- bbox: `x,y,width,height`;
- point: box center or the nearest mismatch point;
- cells: macro cells touched by the box;
- zoom crops: target, actual, and diff.

Prompt the model to include the nearest `mask_id`, but do not let a box alone count as a finding. It still needs component and evidence.

For PNG/JPG inputs, use `*_combined_overlay.png`, `*_boxes.png`, `*_review_panel.png`, `*_side_by_side.png`, and per-box `*_M*_zoom.png` cards as the main agent-facing artifacts.

## Region Modes

Use `ignore` for OS status/nav safe areas unless app content changed there. Use `strict` for app content. Add project-specific ignore regions for dynamic data, animations, timestamps, cursors, or user-generated content.

For PNG/JPG inputs, pass repeated `--ignore-rect X,Y,W,H` values to the OpenCV script. Ignored rectangles are excluded from masks, boxes, and scoring; if present, the script also writes `*_regions.png`.
