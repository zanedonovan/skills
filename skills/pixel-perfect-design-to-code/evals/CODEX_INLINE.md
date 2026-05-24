# Codex Inline Evals

This eval suite follows the Claude Cookbook shape: input prompt, model output, golden answer, and score. Codex is the inline model under test. The local runner does not call any model API.

## Preset Workflow

Most local runs should use the preset runner instead of the lower-level flags:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py quick
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py report
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py live-smoke
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py live-artifact-smoke
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py live-benchmark --repeat 3
uv run python skills/pixel-perfect-design-to-code/evals/workflow.py live-artifact-benchmark --repeat 3
```

- `quick` runs the deterministic fast pytest eval gates.
- `report` regenerates the side-by-side HTML report from saved answers.
- `live-smoke` captures one live `with_skill`/`without_skill` run, grades it, writes benchmark artifacts, and regenerates the report.
- `live-artifact-smoke` is the same smoke flow, but the no-skill baseline receives the same review artifacts so you can separate skill-instruction value from artifact-grounding value.
- `live-benchmark` runs every case with repeated attempts for production readiness decisions.
- `live-artifact-benchmark` runs the same all-case benchmark while giving the baseline the same review artifacts.

Live presets create or accept a `run_id` and write generated files under `skills/pixel-perfect-design-to-code/evals/runs/<run_id>/`.

## Run One Case

Print a self-contained prompt:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/run_evals.py --print-prompts --case-id ios_header_shift
```

Open the two screenshot files named in the prompt. They are already rendered with the same grid overlay. For manual review, `skills/pixel-perfect-design-to-code/evals/side_by_side.html` also renders clean no-grid diff aids: threshold mask, M1/M2 diff boxes, edge/shape diff, structural heatmap, and zoom crops.

## Codex Answer Format

Codex should return only valid JSON, without Markdown fences:

```json
{
  "findings": [
    {
      "severity": "high|medium|low",
      "cells": ["A1"],
      "mask_id": "M1|none",
      "point": [116, 82],
      "component": "...",
      "difference": "...",
      "evidence": "..."
    }
  ],
  "summary": "one sentence"
}
```

Rules:

- Grade the visual mismatch against the design mock, not implementation code.
- Every finding must include grid cells and concrete evidence.
- Every finding must include `point: x,y`.
- If review boxes are visible, include the nearest `mask_id`; use `mask_id: none` when no box covers the mismatch.
- For position/size mismatches, estimate the pixel delta from nearby grid lines or edge-ruler ticks.
- Ignore the grid overlay itself.
- Ignore OS status/navigation safe-area differences unless app content changed there.
- Do not add speculative differences.

## Save And Grade

Put the Codex output into an answers JSON file:

```json
{
  "answers": [
    {
      "id": "ios_header_shift",
      "answer": {
        "findings": [
          {
            "severity": "medium",
            "cells": ["A1", "B1"],
            "mask_id": "none",
            "point": [116, 82],
            "component": "header title",
            "difference": "shifted down",
            "evidence": "about 8 px too low"
          }
        ],
        "summary": "Header differs."
      }
    }
  ]
}
```

Run the deterministic grader:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/run_evals.py --answers skills/pixel-perfect-design-to-code/evals/sample_answers.json
```

The grader compares the answer with `skills/pixel-perfect-design-to-code/evals/cases.json` golden findings and prints per-case pass/fail plus the total score.
For local quality gates, run the same checks through pytest markers:

```bash
uv run python -m pytest skills/pixel-perfect-design-to-code/evals/tests -m "eval and fast"
uv run python -m pytest skills/pixel-perfect-design-to-code/evals/tests -m "eval and integration"
RUN_LIVE_EVALS=1 uv run python -m pytest skills/pixel-perfect-design-to-code/evals/tests/evals -m "eval and live"
```

### Paired Compare Mode

To run a baseline comparison per case, use:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/run_codex_exec.py --case-id ios_header_shift --run-id manual-ios-header-001 --out skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/answers.json --compare-baseline
uv run python skills/pixel-perfect-design-to-code/evals/run_evals.py --compare --answers skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/answers.json --run-id manual-ios-header-001 --case-id ios_header_shift
```

The `with_skill` run explicitly names `pixel-perfect-design-to-code` in the prompt. In compare mode both runs use clean temporary `--cd` directories so gold files and grader code are not in the agent workspace. The baseline run also adds `--ignore-user-config` and `--ignore-rules` so project-local skill files are not available. Use `--with-skill-cd /path/to/clean-dir` or `--without-skill-cd /path/to/clean-dir` to choose those workspaces yourself.
Use `--repeat N` on `run_codex_exec.py` when you need stability signal; repeated attempts are written as attempts and `run_evals.py` marks a case `flaky` when one mode disagrees across attempts. Use `--without-skill-images full` to run the artifact baseline with the same attached review artifacts as the skill run.
Preset live workflows write artifacts under `skills/pixel-perfect-design-to-code/evals/runs/<run_id>/`.

When `--compare-baseline` is enabled, each row keeps both modes:

```json
{
  "id": "ios_header_shift",
  "with_skill": {...},
  "with_skill_run": {
    "run_id": "manual-ios-header-001",
    "duration_ms": 1200.5,
    "token_count": 1234,
    "transcript": "skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/transcripts/ios_header_shift_with_skill_last_message.json"
  },
  "without_skill": {...},
  "without_skill_run": {
    "run_id": "manual-ios-header-001",
    "duration_ms": 980.4,
    "token_count": 1040,
    "transcript": "skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/transcripts/ios_header_shift_without_skill_last_message.json"
  }
}
```

For review, `run_codex_exec.py` also writes transcript files under `--transcripts-dir` for every execution. It runs `codex exec --json`, stores JSONL events in each transcript, and `run_evals.py` fails a visual-diff answer when the trace does not prove the expected skill activation decision, shows tool calls, or shows access to eval/golden artifacts.

### Benchmarks and Outliers

Use:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/run_evals.py --compare --answers skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/answers.json --run-id manual-ios-header-001 --benchmark-out skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/benchmark.json --grading-out skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/grading.json
```

In `--compare` mode every selected case must include both `with_skill` and `without_skill`.
A missing baseline answer is treated as an invalid eval run instead of a passing `with_skill`-only result.

`benchmark.json` contains pass rates, average scores, duration/tokens and deltas, plus pattern buckets:
- `always_pass`
- `always_fail`
- `improved`
- `regressed`
- `flaky`

and top outliers by duration/token counts.

## Skill Development Loop

Use evals to improve the skill instructions, not to replace visual QA.

Store skill-quality cases in `skills/pixel-perfect-design-to-code/evals/cases.json`. Each case should include the prompt/input, expected assertions or golden findings, any image paths, and review notes. If the host repo uses a different fixture file name, keep its schema compatible with this shape and document the alias.

Run every case in pairs:

- `with_skill` against `without_skill`; or
- current skill version against the previous released version.

Capture both outputs with timing, token counts, grading details, and execution transcripts. Keep transcripts as generated review artifacts; do not hand-edit them.

After the first exploratory run, write concrete assertions based on the real failure modes. Prefer script grading for mechanical checks such as JSON shape, required fields, coordinates, mask ids, and banned false alarms. Use an LLM judge only for semantic quality checks that scripts cannot measure reliably.

Aggregate each run into `benchmark.json` with pass rate, average score, token count, duration, and deltas between modes or versions. Review patterns, not just pass rate:

- `always_pass`;
- `always_fail`;
- `improved`;
- `regressed`;
- `flaky`;
- outliers by duration, token count, and score delta.

`flaky` means repeated runs of the same case and mode disagree. A normal `with_skill` pass plus `without_skill` fail is an improvement signal, not flakiness.

For production readiness decisions, use `--production-gate` with compare-mode
grading. The gate fails unless every selected case has a baseline, `with_skill`
passes every case, and repeated attempts produce no `regressed` or `flaky`
patterns. You can tighten release criteria with `--min-score-delta`.

Require human review before accepting a benchmark result. The reviewer should inspect failed assertions, surprising passes, output transcripts, and any outlier cases. Update `SKILL.md` from failed assertions, human feedback, and execution transcripts, then rerun the affected cases.

## Optional Codex Exec Runner

To run a live CLI model answer instead of manually copying text, use:

```bash
uv run python skills/pixel-perfect-design-to-code/evals/run_codex_exec.py --case-id ios_header_shift --run-id manual-ios-header-001 --out skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/answers.json
uv run python skills/pixel-perfect-design-to-code/evals/run_evals.py --answers skills/pixel-perfect-design-to-code/evals/runs/manual-ios-header-001/answers.json --run-id manual-ios-header-001 --case-id ios_header_shift
```

The runner calls `codex exec` with `--image` for the target and implementation screenshots, captures `--output-last-message`, parses it as JSON, and updates the answers JSON. Unit tests use a fake Codex binary; real runs may use model quota.
