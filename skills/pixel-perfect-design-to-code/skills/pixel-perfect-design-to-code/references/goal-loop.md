# Goal Loop

Use this reference when the user asks for `/goal`, maximum visual convergence, repeated pixel-perfect fixing, or resume-safe iteration.

## Meaning Of `/goal`

`/goal` is a skill convention, not a Codex platform command. It tells the agent to run a closed loop:

1. compare the target design screenshot to the current implementation screenshot;
2. produce visual findings with grid cells, mask ids, points, evidence, and likely code fixes;
3. patch the implementation;
4. re-render the implementation screenshot;
5. compute a verified deterministic score and reject regressions;
6. repeat until the iteration budget is used, the score plateaus, or no meaningful findings remain.

Use `/goal` when the user wants convergence, not just diagnosis. For a one-shot review, do one compare pass and return findings.

## Required Inputs

Ask or infer:

- target/design screenshot path;
- current implementation screenshot path or render command;
- viewport/device size;
- max iterations, for example `--max-iterations 5`;
- dynamic regions to ignore, such as status bars, clocks, random data, cursor, animations, or user content.

## Iteration Artifacts

Write each run into a stable folder, for example:

```text
.pixel-goal/
  state.md
  report.html
  review-pairs/
    iter-00_side_by_side.svg
    iter-01_side_by_side.svg
  iter-00/
    current.png
    iter-00_metadata.json
    iter-00_review_panel.png
    iter-00_side_by_side.png
    iter-00_boxes.png
    iter-00_combined.png
    iter-00_combined_overlay.png
    iter-00_structural_heatmap.png
  iter-01/
    current.png
    iter-01_metadata.json
    iter-01_review_panel.png
    iter-01_side_by_side.png
    iter-01_boxes.png
    iter-01_combined.png
```

Keep all screenshots. Do not overwrite previous iterations; the final report must show the whole trajectory.

For every iteration, also generate an agent-facing side-by-side image. Pass that image to the reviewing agent together with the separate target/current screenshots and all mask/box/crop artifacts. The side-by-side image gives orientation; the separate artifacts give detailed evidence.

## Score Gate

The OpenCV tool emits `score.source`, `score.overall`, diff ratios, pixel counts, boxes, regression metadata, and PNG review artifacts for PNG/JPG inputs. A perfect visual match is `1.0`; lower means more visual difference.

Do not hand-write or patch score metadata, mask images, box overlays, or zoom crops. These artifacts are evidence only when they come from the scorer/browser comparison command. If a score lacks scorer provenance, pixel-count fields, or hashes for the exact target/current files, treat it as unverified and do not accept it as a `/goal` improvement.

For trusted score-gated runs, the scorer must also sign metadata with an HMAC key that the coding agent cannot read or write. Store `PIXEL_GOAL_ATTESTATION_KEY` only in the trusted scorer/report job, run scorer commands with `--require-attestation-key`, and run report commands with `--require-attestation`. With `--require-attestation-key`, previous metadata used by `--previous-metadata` must be signed too. Hidden files inside the workspace are not a trust boundary; if the agent can discover the key or modify the trusted scorer, signed metadata is not trustworthy.

Baseline:

```bash
uv run scripts/opencv_diff_boxes.py --target target.png --actual .pixel-goal/iter-00/current.png --out-dir .pixel-goal/iter-00 --prefix iter-00 --require-attestation-key
```

Use `--ignore-rect X,Y,W,H` for dynamic/non-app regions such as status bars, clocks, random avatars, cursors, animations, or nav bars. Repeat the flag for multiple regions.

Next iteration:

```bash
uv run scripts/opencv_diff_boxes.py --target target.png --actual .pixel-goal/iter-01/current.png --out-dir .pixel-goal/iter-01 --prefix iter-01 --previous-metadata .pixel-goal/iter-00/iter-00_metadata.json --require-improvement --fail-on-regression --require-attestation-key
```

Only accept an iteration if:

- `score.source`, score pixel-count fields, target/current hashes, and trusted HMAC attestation prove the metadata came from the scorer for the reported files;
- `score.overall` increases by the configured minimum;
- `score.regressed` is false;
- no new visible mismatch appears outside the intended patch area;
- the remaining findings are genuinely smaller or lower severity.

If the score worsens, fix the regression or revert the last patch before continuing. Do not hide differences with masks or ignored regions unless the region is genuinely dynamic/non-app content.

## Context Compaction Recovery

After every iteration, update `.pixel-goal/state.md`. This file is the compact context to load after a conversation is summarized or resumed.

It must include:

- goal and target screenshot;
- render command;
- max iterations and current iteration;
- latest score and best score;
- accepted changes and rejected/regressed attempts;
- pending findings with cells, points, and mask ids;
- ignored dynamic regions and tolerances;
- current screenshot and metadata paths;
- side-by-side review image paths;
- final or current report path;
- the next concrete action.

After compaction, read `.pixel-goal/state.md` first, then open only the latest report or latest screenshots needed for the next patch. Do not rely on the old chat transcript for the active goal state.

## Checkpoint Discipline

Skills do not have a portable always-on “active skill hook”. Make the checkpoint explicit and hard to skip:

1. after each score run, immediately run `goal_report.py --state-out .pixel-goal/state.md`;
2. before any new code patch, verify `state.md` names the latest iteration screenshot and metadata;
3. if state is stale, update state before patching;
4. if the environment supports hooks, configure the hook to run the same checkpoint or freshness check, not a separate state format.

Verified score gates are stateful by contract: when `goal_report.py` runs with `--require-verified-score` or `--require-attestation`, it must also receive `--state-out`, or the command exits before producing an accepted report.

## Final Report

At the end, create a HTML report:

```bash
uv run python scripts/goal_report.py --target target.png --screenshot .pixel-goal/iter-00/current.png --metadata .pixel-goal/iter-00/iter-00_metadata.json --screenshot .pixel-goal/iter-01/current.png --metadata .pixel-goal/iter-01/iter-01_metadata.json --width 390 --height 844 --max-iterations 5 --out .pixel-goal/report.html --state-out .pixel-goal/state.md --pair-out-dir .pixel-goal/review-pairs --require-verified-score --require-attestation
```

Return the report path to the user with a short summary of the final score, best iteration, remaining differences, and any accepted tradeoffs.
