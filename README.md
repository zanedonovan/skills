# Skills For Real Engineers

<img src=".github/assets/readme/ai-skills-for-real-engineers.png" alt="AI Skills for Real Engineers" width="320">

Codex agent skills for real engineering work - not vibe coding.

This repository is a monorepo for reusable Codex Agent Skills. Each skill gets
its own workspace under `skills/<skill-name>/`. The installable bundle lives in a
nested `skills/<skill-name>/skills/<skill-name>/` directory, while evals,
fixtures, tests, and generated run outputs live beside it and are not copied into
the installed skill.

The current production skill is `pixel-perfect-design-to-code`. It helps Codex
compare target design screenshots against implementation screenshots and report
visual mismatches with concrete regions, pixel evidence, and actionable fixes.

## Contents

- `skills/README.md` - collection index and rules for adding new skills.
- `skills/pixel-perfect-design-to-code/` - workspace for the pixel-perfect skill.
- `skills/pixel-perfect-design-to-code/skills/pixel-perfect-design-to-code/` - installable Agent Skill bundle with `SKILL.md`, `agents/`, `scripts/`, `references/`, and `assets/`.
- `skills/pixel-perfect-design-to-code/evals/` - eval suite for this skill: cases, prompts, fixtures, local support package, tests, and generated outputs.

## Repository Boundary

```text
skills/
  README.md
  pixel-perfect-design-to-code/
    skills/
      pixel-perfect-design-to-code/
        SKILL.md
        agents/
        scripts/
        references/
        assets/
    evals/
      cases.json
      prompts/
      fixtures/
      mobile_grid_overlay/
      public/
      tests/
      runs/
```

The installable skill bundle is self-contained. Paths inside `SKILL.md` are
relative to the nested installable bundle. The heavier benchmark and eval
workspace stays beside the bundle, but does not become part of the installed
skill. Future skills should follow the same workspace shape.

Generated artifacts are ignored by default, including local run directories,
transcripts, review artifacts, generated HTML reports, benchmark outputs, grading
outputs, and `codex exec` answer captures.

## Install

Install the skill locally from this repository:

```bash
rsync -a --delete --delete-excluded --exclude '__pycache__' --exclude '*.pyc' --exclude '.venv' --exclude 'uv.lock' skills/pixel-perfect-design-to-code/skills/pixel-perfect-design-to-code/ /Users/lee/.codex/skills/pixel-perfect-design-to-code/
```

Install from a GitHub repo path after publishing:

```bash
python /Users/lee/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py --repo OWNER/REPO --path skills/pixel-perfect-design-to-code/skills/pixel-perfect-design-to-code
```

## Grid Profiles

- `universal` - 4x8 macro grid, 8pt rhythm, ruler labels, and center lines.
- `ios` - universal grid plus common modern iPhone safe-area bands.
- `android` - universal grid plus common status and navigation bands.
- `dense` - 4pt rhythm for small spacing differences.
- `pixel` - 1px measurement grid with 8px major lines for exact deltas.

The grid has three scales: macro cells such as `A1` through `D8` for stable text
localization, an 8/32pt measurement layer for estimating offsets, and edge rulers
for counting pixel deltas. Use the `pixel` profile for strict pixel-perfect
checks.

## Quick Start

Common eval scenarios are available through the preset runner:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py quick
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py report
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py live-smoke
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py live-benchmark --repeat 3
```

`quick` runs fast local pytest gates. `report` rebuilds the HTML report.
`live-smoke` runs one live `with_skill` and `without_skill` case, then writes
answers, grading, benchmark data, and transcripts. `live-artifact-smoke` gives
the baseline the same review layers while still forbidding skill use.

Generate an overlay for a screenshot size:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/mobile_grid_overlay/cli.py --width 390 --height 844 --profile ios --out skills/pixel-perfect-design-to-code/skills/pixel-perfect-design-to-code/assets/grid-overlays/my_ios_grid.svg
```

Generate a pixel-perfect overlay:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/mobile_grid_overlay/cli.py --width 390 --height 844 --profile pixel --out skills/pixel-perfect-design-to-code/skills/pixel-perfect-design-to-code/assets/grid-overlays/my_pixel_grid.svg
```

Embed a screenshot under a grid:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/mobile_grid_overlay/cli.py --width 390 --height 844 --profile ios --screenshot screenshots/actual.png --out skills/pixel-perfect-design-to-code/skills/pixel-perfect-design-to-code/assets/grid-overlays/actual_with_grid.svg
```

Generate synthetic fixture pairs:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/generate_fixtures.py
```

Print the prompt for one Codex inline eval case:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/run_evals.py --print-prompts --case-id ios_header_shift
```

Grade a saved answer file:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/run_evals.py --answers skills/pixel-perfect-design-to-code/evals/sample_answers.json
```

Run one live case through Codex CLI:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/run_codex_exec.py --case-id ios_header_shift --run-id manual-ios-header-001 --out skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/answers.json
uv run python skills/pixel-perfect-design-to-code/evals/run_evals.py --answers skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/answers.json --run-id manual-ios-header-001 --case-id ios_header_shift
```

Run one comparison case and write metrics:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/run_codex_exec.py --case-id ios_header_shift --run-id manual-ios-header-001 --out skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/answers.json --compare-baseline
uv run python skills/pixel-perfect-design-to-code/evals/run_evals.py --compare --answers skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/answers.json --run-id manual-ios-header-001 --case-id ios_header_shift --grading-out skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/grading.json --benchmark-out skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/benchmark.json
```

In comparison mode, the `with_skill` prompt explicitly asks Codex to use
`$pixel-perfect-design-to-code`. The runner passes `skills.config` evidence to
`codex exec`; both branches run from clean temporary working directories, and
the baseline also gets `--ignore-user-config` and `--ignore-rules`.

For stability checks, add `--repeat N`. Benchmark output marks a case as
`flaky` when repeated attempts for the same mode disagree on score, pass status,
or misses. Production gates require a baseline for every selected case, a 100%
`with_skill` pass rate, no regressions, and no flaky repeated attempts.

Run deterministic eval gates:

```bash
uv run python -m pytest skills/pixel-perfect-design-to-code/evals/tests -m "eval and fast"
uv run python -m pytest skills/pixel-perfect-design-to-code/evals/tests -m "eval and integration"
RUN_LIVE_EVALS=1 uv run python -m pytest skills/pixel-perfect-design-to-code/evals/tests/evals -m "eval and live"
```

Generate the HTML report with prompts, side-by-side screenshots, and agent
output:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/generate_side_by_side.py
```

The HTML report has independent review layers: strict diff mask without the grid,
threshold diff mask, connected-component boxes named `M1`, `M2`, edge and shape
diff overlays, structural heatmap, and zoom crops for each box.

For real PNG or JPG screenshots, the skill uses:

```text
skills/pixel-perfect-design-to-code/skills/pixel-perfect-design-to-code/scripts/opencv_diff_boxes.py
```

The script writes standalone PNG review artifacts for the agent, including masks,
overlays, boxes, side-by-side panels, review panels, and zoom cards. Dynamic
regions can be excluded with repeatable `--ignore-rect X,Y,W,H` arguments.

## Eval Format

Each eval has an input prompt, model output, golden answer, and score. In this
project, Codex inline mode is the model under test. Golden answers are stored as
`expected_findings`, and scores are computed by a code-based grader.

An expected finding in `skills/pixel-perfect-design-to-code/evals/cases.json`
has a `label`, `region_terms`, `evidence_terms`, and a `target` as either a
`point` or a `box`.

A finding passes when the model returns valid JSON with `findings[]`, identifies
the expected region, includes the expected evidence, and points near the target
coordinates. Fine-grained cases can set a strict `tolerance`; otherwise the
default tolerance is `32px`.

Prompts and reports use neutral `case-...` labels and `public/...` image aliases
so golden answers are not leaked through descriptive ids or filenames.

Live runner traces preserve `codex exec --json` events. Current Codex CLI JSONL
does not emit a dedicated `skill_activated` event, so `with_skill` is gated
through explicit setup evidence: `skills.config`, install path, `SKILL.md` hash,
and command override. The grader also fails a run when the trace shows forbidden
tool calls or access to eval and golden artifacts.

Cookbook pattern source: [Building evals | Claude Cookbook](https://platform.claude.com/cookbook/misc-building-evals).
