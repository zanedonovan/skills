"""Run cookbook-style inline Codex mobile visual-diff evals.

This runner grades pre-captured answers and optionally compares outputs from two
run modes (for example: with-skill vs without-skill). It intentionally avoids
any model API usage and is therefore stable in CI.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
EVALS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EVALS_ROOT))

from mobile_grid_overlay.evals import build_prompt, grade_answer, load_cases_json


@dataclass(frozen=True)
class EvalModeResult:
    case_id: str
    mode: str
    score: float
    passed: bool
    matched_findings: tuple[str, ...]
    missed_findings: tuple[str, ...]
    false_alarms: tuple[str, ...]
    schema_errors: tuple[str, ...] = ()
    trace_errors: tuple[str, ...] = ()
    setup_errors: tuple[str, ...] = ()
    duration_ms: float | None = None
    token_count: int | None = None
    transcript: str | None = None
    attempt_index: int | None = None
    attempt_count: int = 1
    flaky: bool = False
    attempt_results: tuple[EvalModeResult, ...] = ()


@dataclass(frozen=True)
class CaseComparison:
    case_id: str
    with_skill: EvalModeResult | None
    without_skill: EvalModeResult | None
    delta: dict[str, float | int | None]
    label: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print or grade inline Codex visual-diff evals.")
    parser.add_argument("--cases", default=str(EVALS_ROOT / "cases.json"))
    parser.add_argument("--answers", default=str(EVALS_ROOT / "sample_answers.json"))
    parser.add_argument("--template", default=str(EVALS_ROOT / "prompts" / "mobile_visual_diff.md"))
    parser.add_argument("--print-prompts", action="store_true")
    parser.add_argument("--case-id", help="Only print or grade one case.")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Expect with_skill/without_skill answer payloads.",
    )
    parser.add_argument(
        "--grading-out",
        help="Write per-case grading details to this path.",
    )
    parser.add_argument(
        "--benchmark-out",
        help="Write aggregate benchmark summary to this path.",
    )
    parser.add_argument("--run-id", help="Stable id for grading and benchmark artifacts.")
    parser.add_argument(
        "--production-gate",
        action="store_true",
        help=(
            "Fail unless the selected cases meet release gates: complete with/without "
            "comparison, no regressions, no flaky cases, and full with-skill pass rate."
        ),
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        help="Minimum with-skill pass rate required when enforcing gates.",
    )
    parser.add_argument(
        "--min-score-delta",
        type=float,
        help="Minimum average with-skill minus without-skill score delta required by gates.",
    )
    parser.add_argument(
        "--allow-regressions",
        action="store_true",
        help="Allow regressed cases when enforcing production gates.",
    )
    parser.add_argument(
        "--allow-flaky",
        action="store_true",
        help="Allow flaky repeated attempts when enforcing production gates.",
    )
    parser.add_argument(
        "--allow-missing-baseline",
        action="store_true",
        help="Allow selected cases without without_skill baseline payloads in production gates.",
    )
    args = parser.parse_args(argv)
    _validate_thresholds(args)

    cases = load_cases_json(Path(args.cases))
    if args.case_id:
        cases = [case for case in cases if case.id == args.case_id]
        if not cases:
            raise SystemExit(f"case not found: {args.case_id}")

    if args.print_prompts:
        template = Path(args.template).read_text(encoding="utf-8")
        for case in cases:
            print(f"===== {case.id} =====")
            print(build_prompt(case, template))
        return 0

    answers, source_run_metadata = _load_answers(Path(args.answers))
    run_id = args.run_id or _source_run_id(source_run_metadata) or _new_run_id("grade")

    with_results: list[EvalModeResult] = []
    without_results: list[EvalModeResult] = []
    comparisons: list[CaseComparison] = []

    for case in cases:
        bundle = answers.get(case.id, {})
        has_comparison_payload = args.compare or _is_comparison_payload(bundle)
        if args.compare and not _has_mode_payload(bundle, "without_skill"):
            raise SystemExit(f"missing without_skill answer for compare case: {case.id}")

        with_attempts = _grade_case_attempts(
            case,
            mode="with_skill",
            allow_missing=False,
            attempt_rows=_attempt_rows(bundle, "with_skill"),
        )
        with_result = _aggregate_results(case.id, "with_skill", with_attempts)
        without_result = None
        if has_comparison_payload:
            without_attempts = _grade_case_attempts(
                case,
                mode="without_skill",
                allow_missing=True,
                attempt_rows=_attempt_rows(bundle, "without_skill"),
            )
            without_result = _aggregate_results(case.id, "without_skill", without_attempts)

        if has_comparison_payload:
            comparison = _build_case_comparison(case.id, with_result, without_result)
            comparisons.append(comparison)
            _print_case_comparison(comparison)
        else:
            _print_single_result(with_result)

        with_results.append(with_result)
        if without_result is not None:
            without_results.append(without_result)

    total_cases = len(cases)
    passed = sum(1 for result in with_results if result.passed)
    print(f"Score: {passed}/{total_cases} cases passed")

    benchmark = _build_benchmark(
        total_cases=total_cases,
        with_results=with_results,
        without_results=without_results,
        comparisons=comparisons,
        run_id=run_id,
        source_run_metadata=source_run_metadata,
    )
    production_gate = _evaluate_production_gate(
        benchmark,
        args=args,
        comparison_count=len(comparisons),
        total_cases=total_cases,
    )
    if production_gate["enabled"]:
        benchmark["production_gate"] = production_gate
        if production_gate["passed"]:
            print("Production gate: PASS")
        else:
            print("Production gate: FAIL")
            for error in production_gate["errors"]:
                print(f"  {error}")

    if args.grading_out:
        _write_grading_out(
            args.grading_out,
            comparisons,
            with_results,
            run_id=run_id,
            source_run_metadata=source_run_metadata,
        )
    if args.benchmark_out:
        _write_benchmark_out(args.benchmark_out, benchmark)

    if passed != total_cases:
        return 1
    if production_gate["enabled"] and not production_gate["passed"]:
        return 1
    return 0


def _load_answers(path: Path) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("answers") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("answers JSON must be a list or an object with an 'answers' list")
    parsed: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("answer rows must be objects")
        case_id = row.get("id")
        if not isinstance(case_id, str):
            raise ValueError("answer row is missing string id")
        parsed[case_id] = row
    metadata = payload.get("run_metadata") if isinstance(payload, dict) else {}
    return parsed, metadata if isinstance(metadata, dict) else {}


def _validate_thresholds(args: argparse.Namespace) -> None:
    for attr in ("min_pass_rate",):
        value = getattr(args, attr)
        if value is not None and not 0.0 <= value <= 1.0:
            raise SystemExit(f"--{attr.replace('_', '-')} must be between 0.0 and 1.0")


def _evaluate_production_gate(
    benchmark: dict[str, object],
    *,
    args: argparse.Namespace,
    comparison_count: int,
    total_cases: int,
) -> dict[str, object]:
    enabled = _production_gate_enabled(args)
    min_pass_rate = args.min_pass_rate
    min_score_delta = args.min_score_delta
    if args.production_gate:
        min_pass_rate = 1.0 if min_pass_rate is None else min_pass_rate
        min_score_delta = 0.0 if min_score_delta is None else min_score_delta
    if not enabled:
        return {"enabled": False, "passed": True, "errors": ()}

    patterns = benchmark.get("patterns") if isinstance(benchmark.get("patterns"), dict) else {}
    with_skill = benchmark.get("with_skill") if isinstance(benchmark.get("with_skill"), dict) else {}
    delta = benchmark.get("delta") if isinstance(benchmark.get("delta"), dict) else {}
    errors: list[str] = []

    pass_rate = _number(with_skill.get("pass_rate"))
    if min_pass_rate is not None and pass_rate < min_pass_rate:
        errors.append(
            f"with_skill pass_rate {pass_rate:.3f} < required {min_pass_rate:.3f}"
        )

    score_delta = _number(delta.get("score"))
    if min_score_delta is not None and score_delta < min_score_delta:
        errors.append(
            f"average score delta {score_delta:.3f} < required {min_score_delta:.3f}"
        )

    missing_baselines = max(0, total_cases - comparison_count)
    if missing_baselines and not args.allow_missing_baseline:
        errors.append(f"missing without_skill baseline for {missing_baselines} case(s)")

    regressed = tuple(patterns.get("regressed", ()) if isinstance(patterns, dict) else ())
    if regressed and not args.allow_regressions:
        errors.append(f"regressed cases: {', '.join(str(case) for case in regressed)}")

    flaky = tuple(patterns.get("flaky", ()) if isinstance(patterns, dict) else ())
    if flaky and not args.allow_flaky:
        errors.append(f"flaky cases: {', '.join(str(case) for case in flaky)}")

    return {
        "enabled": True,
        "passed": not errors,
        "errors": tuple(errors),
        "requirements": {
            "min_pass_rate": min_pass_rate,
            "min_score_delta": min_score_delta,
            "allow_regressions": args.allow_regressions,
            "allow_flaky": args.allow_flaky,
            "allow_missing_baseline": args.allow_missing_baseline,
        },
    }


def _production_gate_enabled(args: argparse.Namespace) -> bool:
    return any(
        (
            args.production_gate,
            args.min_pass_rate is not None,
            args.min_score_delta is not None,
        )
    )


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _source_run_id(metadata: dict[str, object]) -> str | None:
    run_id = metadata.get("run_id")
    return run_id if isinstance(run_id, str) and run_id else None


def _new_run_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid4().hex[:8]}"


def _is_comparison_payload(row: dict[str, object]) -> bool:
    return _has_mode_payload(row, "without_skill")


def _has_mode_payload(row: dict[str, object], mode: str) -> bool:
    if mode == "with_skill":
        return "with_skill" in row or "answer" in row or "with_skill_attempts" in row or "attempts" in row
    return "without_skill" in row or "without_skill_attempts" in row


def _attempt_rows(row: dict[str, object], mode: str) -> tuple[dict[str, object], ...]:
    if mode == "with_skill":
        attempts = row.get("with_skill_attempts", row.get("attempts"))
        if isinstance(attempts, list):
            return _normalize_attempt_rows(attempts)
        return (
            {
                "answer": row.get("with_skill", row.get("answer")),
                "run": row.get("with_skill_run", row.get("run")),
            },
        )

    attempts = row.get("without_skill_attempts")
    if isinstance(attempts, list):
        return _normalize_attempt_rows(attempts)
    return (
        {
            "answer": row.get("without_skill"),
            "run": row.get("without_skill_run"),
        },
    )


def _normalize_attempt_rows(raw_attempts: list[object]) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for attempt in raw_attempts:
        if isinstance(attempt, dict) and ("answer" in attempt or "run" in attempt):
            rows.append({"answer": attempt.get("answer"), "run": attempt.get("run")})
        else:
            rows.append({"answer": attempt, "run": None})
    return tuple(rows)


def _grade_case_attempts(
    case,
    *,
    mode: str,
    allow_missing: bool,
    attempt_rows: tuple[dict[str, object], ...],
) -> tuple[EvalModeResult, ...]:
    if not attempt_rows:
        return ()
    attempt_count = len(attempt_rows)
    results: list[EvalModeResult] = []
    for index, attempt in enumerate(attempt_rows, start=1):
        result = _grade_case(
            case,
            attempt.get("answer"),
            attempt.get("run"),
            mode=mode,
            allow_missing=allow_missing,
            attempt_index=index if attempt_count > 1 else None,
            attempt_count=attempt_count,
        )
        if result is not None:
            results.append(result)
    return tuple(results)


def _aggregate_results(
    case_id: str,
    mode: str,
    results: tuple[EvalModeResult, ...],
) -> EvalModeResult | None:
    if not results:
        return None
    if len(results) == 1:
        return results[0]

    score = _average([result.score for result in results]) or 0.0
    duration_ms = _average([result.duration_ms for result in results])
    token_average = _average([result.token_count for result in results])
    flaky = _attempts_are_flaky(results)
    return EvalModeResult(
        case_id=case_id,
        mode=mode,
        score=round(score, 3),
        passed=all(result.passed for result in results),
        matched_findings=_unique_terms(result.matched_findings for result in results),
        missed_findings=_unique_terms(result.missed_findings for result in results),
        false_alarms=_unique_terms(result.false_alarms for result in results),
        schema_errors=_unique_terms(result.schema_errors for result in results),
        trace_errors=_unique_terms(result.trace_errors for result in results),
        setup_errors=_unique_terms(result.setup_errors for result in results),
        duration_ms=duration_ms,
        token_count=round(token_average) if token_average is not None else None,
        attempt_count=len(results),
        flaky=flaky,
        attempt_results=results,
    )


def _unique_terms(groups: object) -> tuple[str, ...]:
    values: list[str] = []
    for group in groups:
        for value in group:
            if value not in values:
                values.append(value)
    return tuple(values)


def _attempts_are_flaky(results: tuple[EvalModeResult, ...]) -> bool:
    signatures = {
        (
            result.passed,
            result.score,
            result.matched_findings,
            result.missed_findings,
            result.false_alarms,
            result.schema_errors,
            result.trace_errors,
            result.setup_errors,
        )
        for result in results
    }
    return len(signatures) > 1


def _grade_case(
    case,
    raw_answer: object | None,
    raw_meta: object | None,
    *,
    mode: str,
    allow_missing: bool,
    attempt_index: int | None = None,
    attempt_count: int = 1,
) -> EvalModeResult | None:
    if raw_answer is None:
        if allow_missing:
            return None
        return EvalModeResult(
            case_id=case.id,
            mode=mode,
            score=0.0,
            passed=False,
            matched_findings=(),
            missed_findings=(),
            false_alarms=(),
            schema_errors=(),
            attempt_index=attempt_index,
            attempt_count=attempt_count,
        )

    result = grade_answer(case, raw_answer)
    meta = _extract_meta(raw_meta)
    trace_errors = meta.get("trace_errors", ())
    trace_errors = trace_errors if isinstance(trace_errors, tuple) else ()
    setup_errors = _skill_setup_errors(meta, mode=mode)
    blocking_errors = trace_errors + setup_errors
    score = 0.0 if blocking_errors else result.score
    return EvalModeResult(
        case_id=case.id,
        mode=mode,
        score=score,
        passed=result.passed and not blocking_errors,
        matched_findings=result.matched_findings,
        missed_findings=result.missed_findings,
        false_alarms=result.false_alarms,
        schema_errors=result.schema_errors,
        trace_errors=trace_errors,
        setup_errors=setup_errors,
        duration_ms=meta.get("duration_ms"),
        token_count=meta.get("token_count"),
        transcript=meta.get("transcript"),
        attempt_index=attempt_index,
        attempt_count=attempt_count,
    )


def _extract_meta(raw_meta: object | None) -> dict[str, object]:
    if not isinstance(raw_meta, dict):
        return {}
    cleaned: dict[str, object] = {"has_live_run_meta": isinstance(raw_meta.get("run_id"), str)}
    duration_ms = raw_meta.get("duration_ms")
    token_count = raw_meta.get("token_count")
    transcript = raw_meta.get("transcript")
    run_id = raw_meta.get("run_id")
    trace_errors = raw_meta.get("trace_errors")
    skill_setup = raw_meta.get("skill_setup")
    if isinstance(duration_ms, (int, float)):
        cleaned["duration_ms"] = float(duration_ms)
    if isinstance(token_count, (int, float)):
        cleaned["token_count"] = int(token_count)
    if isinstance(transcript, str):
        cleaned["transcript"] = transcript
    if isinstance(run_id, str):
        cleaned["run_id"] = run_id
    if isinstance(skill_setup, dict):
        cleaned["skill_setup"] = skill_setup
    if isinstance(trace_errors, list):
        cleaned["trace_errors"] = _active_trace_errors(trace_errors)
    elif isinstance(trace_errors, tuple):
        cleaned["trace_errors"] = _active_trace_errors(trace_errors)
    return cleaned


def _active_trace_errors(raw_errors: object) -> tuple[str, ...]:
    errors: list[str] = []
    for error in raw_errors:
        message = str(error)
        if not message:
            continue
        if message.startswith("missing actual skill activation trace:"):
            continue
        errors.append(message)
    return tuple(errors)


def _skill_setup_errors(meta: dict[str, object], *, mode: str) -> tuple[str, ...]:
    if mode != "with_skill" or not meta.get("has_live_run_meta"):
        return ()
    setup = meta.get("skill_setup")
    if not isinstance(setup, dict):
        return ("missing with_skill setup evidence",)
    errors: list[str] = []
    if setup.get("required") is not True:
        errors.append("with_skill run did not mark skill setup as required")
    if setup.get("configured") is not True:
        errors.append("with_skill run did not include skills.config override")
    if not isinstance(setup.get("path"), str) or not setup.get("path"):
        errors.append("with_skill setup missing skill path")
    if not isinstance(setup.get("sha256"), str) or not setup.get("sha256"):
        errors.append("with_skill setup missing skill sha256")
    override = setup.get("config_override")
    if not isinstance(override, str) or "skills.config" not in override:
        errors.append("with_skill setup missing skills.config evidence")
    return tuple(errors)


def _build_case_comparison(
    case_id: str,
    with_skill: EvalModeResult | None,
    without_skill: EvalModeResult | None,
) -> CaseComparison:
    delta = _build_delta(with_skill, without_skill)
    label = _case_label(with_skill, without_skill)
    return CaseComparison(
        case_id=case_id,
        with_skill=with_skill,
        without_skill=without_skill,
        delta=delta,
        label=label,
    )


def _build_delta(
    with_skill: EvalModeResult | None,
    without_skill: EvalModeResult | None,
) -> dict[str, float | int | None]:
    if with_skill is None and without_skill is None:
        return {"score": None, "duration_ms": None, "token_count": None}
    if with_skill is None:
        return {"score": -without_skill.score, "duration_ms": None, "token_count": None}
    if without_skill is None:
        return {"score": with_skill.score, "duration_ms": None, "token_count": None}
    return {
        "score": with_skill.score - without_skill.score,
        "duration_ms": _delta_numeric(with_skill.duration_ms, without_skill.duration_ms),
        "token_count": _delta_numeric(with_skill.token_count, without_skill.token_count),
    }


def _delta_numeric(
    left: float | int | None,
    right: float | int | None,
) -> float | int | None:
    if left is None or right is None:
        return None
    return left - right


def _print_single_result(result: EvalModeResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"{status} {result.case_id}: score={result.score:.3f}")
    _print_result_diagnostics(result, indent="  ")


def _print_result_diagnostics(result: EvalModeResult, *, indent: str) -> None:
    if result.attempt_count > 1:
        flaky = "yes" if result.flaky else "no"
        print(f"{indent}attempts: {result.attempt_count} flaky={flaky}")
    if result.missed_findings:
        print(f"{indent}missed: {', '.join(result.missed_findings)}")
    if result.false_alarms:
        print(f"{indent}false alarms: {', '.join(result.false_alarms)}")
    if result.schema_errors:
        print(f"{indent}schema errors: {'; '.join(result.schema_errors)}")
    if result.trace_errors:
        print(f"{indent}trace errors: {'; '.join(result.trace_errors)}")
    if result.setup_errors:
        print(f"{indent}setup errors: {'; '.join(result.setup_errors)}")
    if result.duration_ms is not None:
        print(f"{indent}duration_ms: {result.duration_ms:.1f}")
    if result.token_count is not None:
        print(f"{indent}token_count: {result.token_count}")
    for attempt in result.attempt_results:
        attempt_status = "PASS" if attempt.passed else "FAIL"
        index = attempt.attempt_index or 1
        print(f"{indent}attempt {index}: {attempt_status} score={attempt.score:.3f}")


def _print_case_comparison(comparison: CaseComparison) -> None:
    with_skill = comparison.with_skill
    without_skill = comparison.without_skill
    if with_skill is None and without_skill is None:
        print(f"FAIL {comparison.case_id}: missing answers")
        return
    if without_skill is None:
        assert with_skill is not None
        status = "PASS" if with_skill.passed else "FAIL"
        print(f"{status} {comparison.case_id}: with={with_skill.score:.3f} (with only)")
        _print_result_diagnostics(with_skill, indent="  ")
        return

    assert with_skill is not None
    status = "PASS" if with_skill.passed else "FAIL"
    print(
        f"{status} {comparison.case_id}: "
        f"with={with_skill.score:.3f} ({'PASS' if with_skill.passed else 'FAIL'}) "
        f"without={without_skill.score:.3f} ({'PASS' if without_skill.passed else 'FAIL'}) "
        f"delta={comparison.delta.get('score', 0.0):+.3f}"
    )
    if with_skill.missed_findings:
        print(f"  missed (with): {', '.join(with_skill.missed_findings)}")
    if without_skill.missed_findings:
        print(f"  missed (without): {', '.join(without_skill.missed_findings)}")
    if with_skill.schema_errors:
        print(f"  schema errors (with): {'; '.join(with_skill.schema_errors)}")
    if without_skill.schema_errors:
        print(f"  schema errors (without): {'; '.join(without_skill.schema_errors)}")
    if with_skill.trace_errors:
        print(f"  trace errors (with): {'; '.join(with_skill.trace_errors)}")
    if without_skill.trace_errors:
        print(f"  trace errors (without): {'; '.join(without_skill.trace_errors)}")
    if with_skill.setup_errors:
        print(f"  setup errors (with): {'; '.join(with_skill.setup_errors)}")
    if without_skill.setup_errors:
        print(f"  setup errors (without): {'; '.join(without_skill.setup_errors)}")
    if with_skill.attempt_count > 1 or without_skill.attempt_count > 1:
        print(
            "  attempts(with/without)="
            f"{with_skill.attempt_count}/{without_skill.attempt_count} "
            f"flaky(with/without)={with_skill.flaky}/{without_skill.flaky}"
        )
    if comparison.delta.get("duration_ms") is not None:
        print(f"  duration_ms_delta={comparison.delta['duration_ms']:+.1f}")
    if comparison.delta.get("token_count") is not None:
        print(f"  token_count_delta={comparison.delta['token_count']:+}")
    if with_skill.duration_ms is not None and without_skill.duration_ms is not None:
        print(f"  duration_ms(with/without)={with_skill.duration_ms:.1f}/{without_skill.duration_ms:.1f}")
    if with_skill.token_count is not None and without_skill.token_count is not None:
        print(f"  token_count(with/without)={with_skill.token_count}/{without_skill.token_count}")


def _write_grading_out(
    path: str,
    comparisons: list[CaseComparison],
    with_results: list[EvalModeResult],
    *,
    run_id: str,
    source_run_metadata: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_run": source_run_metadata,
    }
    if comparisons:
        payload["comparisons"] = [_case_to_grading_payload(comparison) for comparison in comparisons]
    if with_results:
        payload["single_results"] = [_result_to_dict(result) for result in with_results]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_benchmark_out(path: str, benchmark: dict[str, object]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(benchmark, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _build_benchmark(
    *,
    total_cases: int,
    with_results: list[EvalModeResult],
    without_results: list[EvalModeResult],
    comparisons: list[CaseComparison],
    run_id: str,
    source_run_metadata: dict[str, object],
) -> dict[str, object]:
    with_scores = [result.score for result in with_results]
    without_scores = [result.score for result in without_results]

    with_durations = [result.duration_ms for result in with_results if result.duration_ms is not None]
    without_durations = [
        result.duration_ms for result in without_results if result.duration_ms is not None
    ]
    with_tokens = [result.token_count for result in with_results if result.token_count is not None]
    without_tokens = [result.token_count for result in without_results if result.token_count is not None]

    with_pass = sum(1 for result in with_results if result.passed)
    without_pass = sum(1 for result in without_results if result.passed)

    always_pass: list[str] = []
    always_fail: list[str] = []
    improved: list[str] = []
    regressed: list[str] = []
    flaky: list[str] = []

    for comparison in comparisons:
        with_skill = comparison.with_skill
        without_skill = comparison.without_skill
        if with_skill is None or without_skill is None:
            continue
        if with_skill.flaky or without_skill.flaky:
            flaky.append(comparison.case_id)
        if with_skill.passed and without_skill.passed:
            always_pass.append(comparison.case_id)
        elif (not with_skill.passed) and (not without_skill.passed):
            always_fail.append(comparison.case_id)
        elif with_skill.score > without_skill.score:
            improved.append(comparison.case_id)
        elif with_skill.score < without_skill.score:
            regressed.append(comparison.case_id)

    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_run": source_run_metadata,
        "totals": {
            "total_cases": total_cases,
            "with_skill_count": len(with_results),
            "without_skill_count": len(without_results),
            "with_skill_pass": with_pass,
            "without_skill_pass": without_pass,
        },
        "with_skill": {
            "pass_rate": _pass_rate(with_pass, len(with_results)),
            "avg_score": _average(with_scores),
            "median_score": _median(with_scores),
            "avg_duration_ms": _average(with_durations),
            "p95_duration_ms": _percentile(with_durations, 95),
            "avg_token_count": _average(with_tokens),
            "p95_token_count": _percentile(with_tokens, 95),
            "max_duration_ms": max(with_durations) if with_durations else None,
            "max_token_count": max(with_tokens) if with_tokens else None,
        },
        "without_skill": {
            "pass_rate": _pass_rate(without_pass, len(without_results)),
            "avg_score": _average(without_scores),
            "median_score": _median(without_scores),
            "avg_duration_ms": _average(without_durations),
            "p95_duration_ms": _percentile(without_durations, 95),
            "avg_token_count": _average(without_tokens),
            "p95_token_count": _percentile(without_tokens, 95),
            "max_duration_ms": max(without_durations) if without_durations else None,
            "max_token_count": max(without_tokens) if without_tokens else None,
        },
        "delta": {
            "score": _average(_comparison_deltas(comparisons, "score")),
            "duration_ms": _average(_comparison_deltas(comparisons, "duration_ms")),
            "token_count": _average(_comparison_deltas(comparisons, "token_count")),
            "pass_rate": _pass_rate(
                len([comparison for comparison in comparisons if _is_passing(comparison.with_skill)]),
                len([comparison for comparison in comparisons if comparison.with_skill is not None]),
            )
            - _pass_rate(
                len([comparison for comparison in comparisons if _is_passing(comparison.without_skill)]),
                len([comparison for comparison in comparisons if comparison.without_skill is not None]),
            ),
        },
        "patterns": {
            "always_pass": sorted(always_pass),
            "always_fail": sorted(always_fail),
            "improved": sorted(improved),
            "regressed": sorted(regressed),
            "flaky": sorted(flaky),
        },
        "outliers": {
            "with_skill_duration_ms": _top_outliers(with_results, lambda result: result.duration_ms),
            "without_skill_duration_ms": _top_outliers(
                without_results, lambda result: result.duration_ms
            ),
            "with_skill_token_count": _top_outliers(with_results, lambda result: result.token_count),
            "without_skill_token_count": _top_outliers(without_results, lambda result: result.token_count),
            "duration_delta_ms": _top_deltas(
                comparisons, lambda delta: delta["duration_ms"], metric="duration_ms"
            ),
            "token_count_delta": _top_deltas(
                comparisons, lambda delta: delta["token_count"], metric="token_count"
            ),
        },
    }


def _comparison_deltas(
    comparisons: list[CaseComparison], key: str
) -> list[float | int]:
    deltas: list[float | int] = []
    for comparison in comparisons:
        value = comparison.delta.get(key)
        if value is None:
            continue
        if isinstance(value, (float, int)):
            deltas.append(float(value))
    return deltas


def _is_passing(result: EvalModeResult | None) -> bool:
    return bool(result and result.passed)


def _top_outliers(
    results: list[EvalModeResult],
    extract: Callable[[EvalModeResult], float | int | None],
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    pairs: list[tuple[str, str, float | int]] = []
    for result in results:
        value = extract(result)
        if value is None:
            continue
        pairs.append((result.case_id, result.mode, value))
    pairs = sorted(pairs, key=lambda pair: pair[2], reverse=True)
    return [
        {"case_id": case_id, "mode": mode, "value": float(value)}
        for case_id, mode, value in pairs[:limit]
    ]


def _top_deltas(
    comparisons: list[CaseComparison],
    extract: Callable[[dict[str, float | int | None]], float | int | None],
    *,
    metric: str,
    limit: int = 3,
) -> list[dict[str, object]]:
    pairs: list[tuple[str, float | int]] = []
    for comparison in comparisons:
        value = extract(comparison.delta)
        if value is None:
            continue
        pairs.append((comparison.case_id, value))
    pairs = sorted(pairs, key=lambda pair: abs(pair[1]), reverse=True)
    return [
        {"case_id": case_id, "metric": metric, "value": float(value)}
        for case_id, value in pairs[:limit]
    ]


def _average(values: list[float | int | None]) -> float | None:
    valid_values = [float(value) for value in values if value is not None]
    if not valid_values:
        return None
    return sum(valid_values) / len(valid_values)


def _median(values: list[float | int | None]) -> float | None:
    valid_values = sorted(float(value) for value in values if value is not None)
    if not valid_values:
        return None
    return _quantile(valid_values, 0.5)


def _percentile(values: list[float | int | None], percentile: int) -> float | None:
    valid_values = sorted(float(value) for value in values if value is not None)
    if not valid_values:
        return None
    if len(valid_values) == 1:
        return valid_values[0]
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be in [0, 100]")
    idx = (len(valid_values) - 1) * (percentile / 100)
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return valid_values[lower]
    weight = idx - lower
    return valid_values[lower] * (1 - weight) + valid_values[upper] * weight


def _quantile(values: list[float], percentile: float) -> float:
    if not 0 <= percentile <= 1:
        raise ValueError("percentile must be in [0.0, 1.0]")
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _pass_rate(passed: int, total: int) -> float:
    return passed / total if total else 0.0


def _case_label(with_skill: EvalModeResult | None, without_skill: EvalModeResult | None) -> str:
    if with_skill and without_skill:
        if with_skill.score > without_skill.score:
            return "improved"
        if with_skill.score < without_skill.score:
            return "regressed"
        return "stable"
    if with_skill:
        return "with_skill_only"
    if without_skill:
        return "without_skill_only"
    return "missing"


def _case_to_grading_payload(comparison: CaseComparison) -> dict[str, object]:
    return {
        "case_id": comparison.case_id,
        "label": comparison.label,
        "delta": comparison.delta,
        "with_skill": _result_to_dict(comparison.with_skill),
        "without_skill": _result_to_dict(comparison.without_skill),
    }


def _result_to_dict(result: EvalModeResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    payload: dict[str, object] = {
        "case_id": result.case_id,
        "mode": result.mode,
        "score": result.score,
        "passed": result.passed,
        "matched_findings": result.matched_findings,
        "missed_findings": result.missed_findings,
        "false_alarms": result.false_alarms,
        "schema_errors": result.schema_errors,
        "trace_errors": result.trace_errors,
        "duration_ms": result.duration_ms,
        "token_count": result.token_count,
        "transcript": result.transcript,
        "attempt_index": result.attempt_index,
        "attempt_count": result.attempt_count,
        "flaky": result.flaky,
    }
    if result.attempt_results:
        payload["attempts"] = [_result_to_dict(attempt) for attempt in result.attempt_results]
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
