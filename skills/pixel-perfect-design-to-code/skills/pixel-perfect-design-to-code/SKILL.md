---
name: pixel-perfect-design-to-code
description: Help Codex make implementation UI match a design mock pixel-perfectly from screenshots. Use when comparing code output against Figma/design/reference screenshots for Android/iOS/mobile apps, locating visual mismatches with grids, masks, M1/M2 boxes, zoom crops, edge/shape diffs, and producing concrete code-fix guidance.
---

# Pixel Perfect Design To Code

## Workflow

Use `/goal` as the explicit iterative mode when the user wants maximum visual convergence between a target design screenshot and the current implementation. `/goal` is a skill-level convention, not a built-in Codex command: it means “render, compare, patch, rerender, and only keep iterations that improve the visual score without regression.” For one-off screenshot diagnosis, use the normal workflow without the iteration loop.

Read `references/goal-loop.md` when a `/goal` loop starts or when context compaction/resume safety matters.

1. Normalize the design screenshot and implementation screenshot to the same viewport size before reviewing.
2. Create two image families:
   - grid images for LLM localization and pixel estimates;
   - clean no-grid images for diff masks and boxes.
3. Show target and implementation side by side before any derived mask.
4. Add independent review layers rather than replacing earlier ones:
   - strict difference overlay;
   - threshold color mask;
   - edge/shape mask;
   - structural heatmap;
   - connected-component boxes labeled `M1`, `M2`, ...;
   - zoom cards with target/actual/diff crops;
   - region-mode overlay for strict app content and ignored status/nav bands.
5. Ask the model to report only real app-content mismatches and to include `cells`, `mask_id`, `point`, `component`, `difference`, `evidence`, and likely code-fix direction.
6. Convert findings into code changes, then re-render and compare again.
7. In `/goal` mode, save every iteration screenshot and metadata under a run directory such as `.pixel-goal/iter-00`, `.pixel-goal/iter-01`, etc. Metadata, masks, boxes, crops, and score fields must come from the scorer/browser comparison command, not from hand-written `apply_patch` edits.
8. Never manually edit `.pixel-goal/state.md`, `*_metadata.json`, diff masks, box overlays, zoom crops, or side-by-side review artifacts. Regenerate them with the scorer/report scripts; if a file is wrong, fix the generating script or rerun the command.
9. In `/goal` mode, track the requested max iterations, score deltas, accepted/rejected changes, ignored dynamic regions, and pending findings in `.pixel-goal/state.md`.
10. In `/goal` mode, run a state checkpoint after every score calculation. Verified/attested report generation must include `--state-out .pixel-goal/state.md`; the report script rejects verified score gates without it. Before making another patch, confirm `.pixel-goal/state.md` names the latest iteration; if not, regenerate it first.
11. In `/goal` mode, generate an agent-facing side-by-side image for every iteration and pass it alongside the separate target screenshot, current screenshot, masks, boxes, crops, report, and state. Do not make the agent reconstruct the comparison from separate files alone.
12. In `/goal` mode, accept the next patch only when the verified deterministic score increases and no new regression is visible. If the score is unverified, do not call it accepted or final.
13. End `/goal` mode with a HTML report containing the target, every iteration screenshot, side-by-side images, verified scores, diff masks, and boxes.
14. Treat generated review artifacts as evidence for the current visual task, not as the product surface.

## Tool Choices

Use `scripts/opencv_diff_boxes.py` as the default path for PNG/JPG screenshots. It is a self-contained `uv` script with inline dependencies, so it can run from an installed skill without the original repository or host project. It produces standalone raster artifacts for agent review: threshold mask, edge mask, combined mask, strict diff, structural heatmap, target/actual mask overlays, `M1...` boxes, side-by-side PNG, review panel PNG, zoom cards, crops, and JSON metadata. Use browser-canvas layers only when the project needs a dependency-free HTML report or when inputs are SVG.

Resolve bundled paths relative to this skill root so the command works from the installed skill or the source checkout.

Do not create or edit state files, score metadata, mask images, box overlays, or crop artifacts by hand. A `/goal` score is verified only when the metadata has scorer provenance such as `score.source: "opencv_diff_boxes"`, pixel-count fields, and hashes for the exact target/current files being reported. Browser-canvas overlays are useful review evidence, but they are not a verified score unless a command writes comparable metadata.

For production runs, require HMAC attestation in addition to provenance and hashes. Set `PIXEL_GOAL_ATTESTATION_KEY` only in the trusted scorer/report environment, not in the agent-readable workspace or shell, and do not commit it. Run the scorer with `--require-attestation-key`; this signs current metadata and rejects unsigned previous metadata used for score gates. Run the final report with `--require-attestation`. If the agent can read the key or edit the trusted scorer before it runs, the attestation boundary is not valid.

If `uv` cannot download/install the inline dependencies, keep the browser-canvas report as the primary fallback and mention that the OpenCV helper could not run.

Run Python commands through `uv run`. For the OpenCV tool, run the bundled script from the skill root:

```bash
uv run scripts/opencv_diff_boxes.py --target target.png --actual actual.png --out-dir out/diff
```

Use JPG inputs the same way. When dynamic/non-app regions should not affect scoring or boxes, add one or more ignored rectangles:

```bash
uv run scripts/opencv_diff_boxes.py --target target.png --actual actual.jpg --out-dir out/diff --ignore-rect 0,0,390,47 --ignore-rect 0,810,390,34
```

For `/goal` iteration gates, compare each new render against the previous score:

```bash
uv run scripts/opencv_diff_boxes.py --target target.png --actual .pixel-goal/iter-01/current.png --out-dir .pixel-goal/iter-01 --prefix iter-01 --previous-metadata .pixel-goal/iter-00/iter-00_metadata.json --require-improvement --fail-on-regression --require-attestation-key
```

For the final user-facing artifact, build the iteration report and compact resume state:

```bash
uv run python scripts/goal_report.py --target target.png --screenshot .pixel-goal/iter-00/current.png --metadata .pixel-goal/iter-00/iter-00_metadata.json --screenshot .pixel-goal/iter-01/current.png --metadata .pixel-goal/iter-01/iter-01_metadata.json --width 390 --height 844 --max-iterations 5 --out .pixel-goal/report.html --state-out .pixel-goal/state.md --pair-out-dir .pixel-goal/review-pairs --require-verified-score --require-attestation --next-step "Fix the remaining CTA vertical centering mismatch."
```

When asking another agent/model to inspect the current state, attach the OpenCV `*_review_panel.png` and `*_side_by_side.png` first, then attach the raw target/current screenshots and any mask/box/crop images. The review panel and side-by-side image are orientation artifacts; masks, overlays, boxes, heatmaps, and crops are evidence artifacts.

Skills are passive instructions, so do not rely on an automatic “active skill hook” being present. Treat the checkpoint command above as the hook: run it after every screenshot score and before the next code patch. If the host environment supports real hooks, point the hook at the same state-checkpoint command rather than duplicating state logic.

## Mask Selection

- Use threshold masks for color/token/fill/opacity differences.
- Use edge/shape masks for corner radius, icons, text baselines, font shape, and tiny shifts.
- Use structural heatmaps for local layout/shape differences that are not pure color changes.
- Build boxes from combined threshold+edge masks so color and shape regressions both get `M` labels.
- Use zoom crops for subtle differences such as 2-4 px text centering, font mismatch, and rounded corners.
- Use overlay PNGs when the agent needs differences drawn directly on top of the source screenshot instead of separate black-background masks.

See `references/layers.md` for layer definitions and tuning notes.

See `references/goal-loop.md` for `/goal` iteration budgeting, score gates, report output, and context-compaction recovery.

See `references/subagents.md` for Spark sub-agent delegation, runtime agent activation, task packets, and review gates.

Use `assets/grid-overlays/` for bundled sample grid overlays when a static reference asset is useful. Generate task-specific overlays from the host project when exact viewport dimensions are required.

## Sub-Agent Delegation

Use the bundled `agents/` TOML profiles as installable templates for this skill's own sub-agent roles. The skill bundle does not register runtime agents automatically; activate them by copying the TOML files into `.codex/agents/` or `~/.codex/agents/`.

When those runtime agents are installed, the main pixel-perfect agent must attempt delegation if code ownership is unclear or multiple independent `M1`, `M2`, ... regions can be explored or patched separately. Keep score gates and state ownership in the main agent. Spark agents may map artifacts to code or make one narrow visual patch, but the main agent must rerender, rerun scorer/report/state, and accept or reject the iteration.

## Code-Fix Guidance

Turn visual findings into concrete implementation changes:

- spacing/position: adjust margin, padding, constraints, alignment, or transform;
- text baseline/centering: adjust line-height, font metrics, padding, or vertical alignment;
- radius/shape: adjust border radius tokens and confirm per-corner behavior;
- color: use the exact design token/value and check opacity;
- missing/extra content: fix conditional rendering, icon assets, z-index, or clipping.

After edits, regenerate the implementation screenshot and rerun the visual layers.

## Validation

Run the host project's normal validation checks after significant changes.
