You are reviewing two mobile app screenshots for visual parity.
Compare the reference design screenshot with the implementation screenshot.
Both screenshots are `{width}x{height}` on `{platform}`.

Reference: first attached image, unannotated
Implementation: second attached image, unannotated
Optional review aids, when present:
- review panel and side-by-side evidence images;
- the same reference and implementation screenshots with a `{profile}` grid overlay;
- strict diff, threshold, edge/shape, combined mask, structural heatmap, box overlay, and zoom crops.

Task:
Find only visual differences between the implementation screenshot and the design mock.
Focus on visible UI differences, not code quality.

Tool restrictions:
- Do not use shell, filesystem, browser, web, code search, or any other external tool.
- Do not inspect repository files, answer files, transcripts, metadata, configs, or source code.
- Use only this prompt and the attached images.
- If a difference cannot be determined from the attached images, do not report it.

Use the unannotated screenshots first. Use review aids only when they help confirm or measure a visible mismatch:
- when grid images are available, name the macro cell or cells, such as A1, B4, D8;
- when box overlays or zoom crops are available, include the nearest `mask_id`; use `mask_id: none` when no box covers the mismatch;
- every finding must include `point: x,y`, an approximate pixel coordinate inside the mismatch, measured from the top-left screenshot corner;
- every finding must include evidence: estimated offset, size difference, color difference, or missing/extra element;
- estimate pixel deltas from the nearest grid lines or edge-ruler ticks when the mismatch is positional or sizing-related;
- ignore differences caused only by review overlays or the grid itself;
- do not report OS status/navigation safe-area differences unless the app content changed there;
- do not describe matching elements unless they help explain a real mismatch.

Return only valid JSON. Do not wrap it in Markdown. Use exactly this shape:

{{
  "findings": [
    {{
      "severity": "high|medium|low",
      "cells": ["A1"],
      "mask_id": "M1|none",
      "point": [x, y],
      "component": "...",
      "difference": "...",
      "evidence": "..."
    }}
  ],
  "summary": "one sentence"
}}
