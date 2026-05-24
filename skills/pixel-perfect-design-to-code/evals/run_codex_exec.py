"""Run live Codex CLI answers for visual-diff eval cases.

This is the optional "model under test" runner. Unit tests use a fake Codex
binary; real runs call `codex exec` and may use network/model quota.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
EVALS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EVALS_ROOT))

from mobile_grid_overlay.evals import (  # noqa: E402
    EvalCase,
    build_prompt,
    load_cases_json,
    public_actual_path,
    public_clean_actual_path,
    public_clean_mock_path,
    public_case_label,
    public_mock_path,
)


PIXEL_SKILL_NAME = "pixel-perfect-design-to-code"
PIXEL_SKILL_DIR = ROOT / "skills" / PIXEL_SKILL_NAME / "skills" / PIXEL_SKILL_NAME
PIXEL_SKILL_FILE = PIXEL_SKILL_DIR / "SKILL.md"


@dataclass(frozen=True)
class CodexExecConfig:
    codex_bin: str
    model: str | None
    sandbox: str
    cwd: Path
    attach_images: bool
    json_trace: bool = True
    extra_args: tuple[str, ...] = ()


_EVENT_KIND_KEYS = ("type", "event", "kind", "item_type")
_CALL_NAME_KEYS = ("name", "tool", "tool_name", "recipient_name", "function", "cmd", "command")
_TOOL_KIND_TERMS = (
    "exec_command",
    "function_call",
    "mcp_call",
    "shell_command",
    "tool_call",
)
_FORBIDDEN_TRACE_TERMS = (
    "adversarial_answers",
    "answers.json",
    "benchmark.json",
    "cases.json",
    "skills/pixel-perfect-design-to-code/evals/cases",
    "skills/pixel-perfect-design-to-code/evals/run_evals.py",
    "expected_findings",
    "fixture definitions",
    "grader code",
    "grading.json",
    "mobile_grid_overlay/evals.py",
    "rounded_corner_fail_answers",
    "sample_answers",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live Codex exec for inline eval cases.")
    parser.add_argument("--cases", default=str(EVALS_ROOT / "cases.json"))
    parser.add_argument("--template", default=str(EVALS_ROOT / "prompts" / "mobile_visual_diff.md"))
    parser.add_argument("--out", default=str(EVALS_ROOT / "codex_exec_answers.json"))
    parser.add_argument("--case-id", action="append", help="Run one case id. Repeatable.")
    parser.add_argument("--all", action="store_true", help="Run all cases. Required when no --case-id is given.")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model")
    parser.add_argument("--sandbox", default="read-only")
    parser.add_argument("--cd", default=str(ROOT))
    parser.add_argument("--run-id", help="Stable id for this eval run. Defaults to a timestamped id.")
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="Run each case twice: with-skill and baseline mode.",
    )
    parser.add_argument("--without-skill-model", help="Model override for baseline run.")
    parser.add_argument(
        "--with-skill-cd",
        help="Clean working directory for with-skill compare runs. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--without-skill-cd",
        help="Clean working directory for baseline run. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--with-skill-extra-args",
        action="append",
        default=[],
        metavar="ARG",
        help="Extra codex args for with-skill run. Repeatable.",
    )
    parser.add_argument(
        "--without-skill-extra-args",
        action="append",
        default=[],
        metavar="ARG",
        help="Extra codex args for baseline run. Repeatable.",
    )
    parser.add_argument(
        "--transcripts-dir",
        default=str(EVALS_ROOT / "transcripts"),
        help="Directory where per-run transcript files are written.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Run each selected case this many times per mode.",
    )
    parser.add_argument(
        "--without-skill-images",
        choices=("clean", "full"),
        default="clean",
        help="Use clean screenshots only, or the same review artifacts as with-skill.",
    )
    parser.add_argument("--no-json-trace", action="store_true", help="Do not pass codex exec --json.")
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without calling Codex.")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")

    run_id = args.run_id or _new_run_id("codex")
    cases = _select_cases(load_cases_json(Path(args.cases)), args.case_id, args.all)
    template = Path(args.template).read_text(encoding="utf-8")
    transcripts_dir = Path(args.transcripts_dir)
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    config = CodexExecConfig(
        codex_bin=args.codex_bin,
        model=args.model,
        sandbox=args.sandbox,
        cwd=Path(args.cd),
        attach_images=not args.no_images,
        json_trace=not args.no_json_trace,
    )

    answers: dict[str, object] = {}
    if Path(args.out).exists():
        answers.update(_load_answers_json(Path(args.out)))

    with_cd_context = _clean_cd_context(args.with_skill_cd, args.compare_baseline)
    baseline_cd_context = _clean_cd_context(args.without_skill_cd, args.compare_baseline)
    with with_cd_context as with_cd, baseline_cd_context as baseline_cd:
        with_cwd = Path(with_cd) if with_cd else None
        baseline_cwd = Path(baseline_cd) if baseline_cd else None
        if with_cwd:
            with_cwd.mkdir(parents=True, exist_ok=True)
        if baseline_cwd:
            baseline_cwd.mkdir(parents=True, exist_ok=True)

        for case in cases:
            base_prompt = build_prompt(case, template)
            with_prompt = _live_prompt(base_prompt)
            baseline_prompt = _baseline_prompt(base_prompt)
            with_run_mode = "with_skill" if args.compare_baseline else "single"
            without_run_mode = (
                "without_skill_full" if args.without_skill_images == "full" else "without_skill"
            )
            with_transcript = _transcript_path(
                transcripts_dir,
                case.id,
                "with_skill" if args.compare_baseline else "single",
                attempt=1,
                repeat=args.repeat,
            )

            command_preview = build_codex_exec_command(
                case,
                config,
                with_transcript,
                run_mode=with_run_mode,
                model_override=config.model,
                extra_args=tuple(args.with_skill_extra_args),
                cwd_override=with_cwd,
            )
            if args.dry_run:
                print(f"===== {case.id} =====")
                print(" ".join(command_preview))
                if args.compare_baseline:
                    baseline_command = build_codex_exec_command(
                        case,
                        config,
                        _transcript_path(
                            transcripts_dir,
                            case.id,
                            "without_skill",
                            attempt=1,
                            repeat=args.repeat,
                        ),
                        run_mode=without_run_mode,
                        model_override=args.without_skill_model,
                        extra_args=tuple(args.without_skill_extra_args),
                        cwd_override=baseline_cwd,
                        ignore_user_config=True,
                        ignore_rules=True,
                    )
                    print(" ".join(baseline_command))
                continue

            with_attempts = []
            for attempt in range(1, args.repeat + 1):
                with_answer, with_meta = run_case(
                    case,
                    with_prompt,
                    config,
                    _transcript_path(
                        transcripts_dir,
                        case.id,
                        "with_skill" if args.compare_baseline else "single",
                        attempt=attempt,
                        repeat=args.repeat,
                    ),
                    run_mode=with_run_mode,
                    run_id=run_id,
                    model_override=config.model,
                    extra_args=tuple(args.with_skill_extra_args),
                    cwd_override=with_cwd,
                )
                with_attempts.append({"answer": with_answer, "run": with_meta})

            if args.compare_baseline:
                payload: dict[str, object] = {"id": case.id}
                if args.repeat == 1:
                    payload["with_skill"] = with_attempts[0]["answer"]
                    payload["with_skill_run"] = with_attempts[0]["run"]
                else:
                    payload["with_skill_attempts"] = with_attempts

                without_attempts = []
                for attempt in range(1, args.repeat + 1):
                    without_answer, without_meta = run_case(
                        case,
                        baseline_prompt,
                        config,
                        _transcript_path(
                            transcripts_dir,
                            case.id,
                            "without_skill",
                            attempt=attempt,
                            repeat=args.repeat,
                        ),
                        run_mode=without_run_mode,
                        run_id=run_id,
                        model_override=args.without_skill_model,
                        extra_args=tuple(args.without_skill_extra_args),
                        cwd_override=baseline_cwd,
                        ignore_user_config=True,
                        ignore_rules=True,
                    )
                    without_attempts.append({"answer": without_answer, "run": without_meta})
                if args.repeat == 1:
                    payload["without_skill"] = without_attempts[0]["answer"]
                    payload["without_skill_run"] = without_attempts[0]["run"]
                else:
                    payload["without_skill_attempts"] = without_attempts
            else:
                payload = {"id": case.id}
                if args.repeat == 1:
                    payload["answer"] = with_attempts[0]["answer"]
                    payload["run"] = with_attempts[0]["run"]
                else:
                    payload["attempts"] = with_attempts

            answers[case.id] = payload
            print(
                f"WROTE {case.id}: {len(with_attempts)} with-skill attempt(s)",
                flush=True,
            )
            if args.compare_baseline:
                with_duration = _sum_attempt_duration(with_attempts)
                if args.repeat == 1:
                    without_duration = _sum_attempt_duration(
                        [{"run": payload.get("without_skill_run")}]
                    )
                else:
                    without_duration = _sum_attempt_duration(payload.get("without_skill_attempts"))
                print(
                    f"  durations (ms): with-skill={with_duration:.1f}, without={without_duration:.1f}",
                    flush=True,
                )

    if not args.dry_run:
        metadata = _build_run_metadata(
            args=args,
            run_id=run_id,
            cases=cases,
            transcripts_dir=transcripts_dir,
            with_cwd=with_cwd,
            baseline_cwd=baseline_cwd,
        )
        write_answers_json(Path(args.out), answers, metadata=metadata)
        print(f"Answers: {args.out}", flush=True)
    return 0


def _select_cases(cases: list[EvalCase], case_ids: list[str] | None, run_all: bool) -> list[EvalCase]:
    if not case_ids and not run_all:
        raise SystemExit("pass --case-id <id> or --all")
    if run_all and case_ids:
        raise SystemExit("use either --all or --case-id, not both")
    if run_all:
        return cases
    requested = set(case_ids or [])
    selected = [case for case in cases if case.id in requested]
    missing = sorted(requested - {case.id for case in selected})
    if missing:
        raise SystemExit(f"case not found: {', '.join(missing)}")
    return selected


def _live_prompt(prompt: str) -> str:
    return "\n".join(
        [
            prompt,
            "",
            "Live-run constraints:",
            "- Use the $pixel-perfect-design-to-code skill for this run.",
            "- Answer the visual-diff task only.",
            "- Do not call tools. Do not run shell commands, read files, browse, search, or inspect the repository.",
            "- Use only the attached images and this prompt as inputs.",
            "- Do not inspect answer files, hidden expected findings, fixture definitions, or grader code.",
            "- Return only valid JSON matching the prompt schema.",
            "- Use the attached screenshots as the source of truth.",
        ]
    )


def _baseline_prompt(prompt: str) -> str:
    return "\n".join(
        [
            prompt,
            "",
            "Baseline run constraints:",
            "- Do not use any Codex skills, including pixel-perfect-design-to-code.",
            "- Do not call tools. Do not run shell commands, read files, browse, search, or inspect the repository.",
            "- Use only the attached images and this prompt as inputs.",
            "- Return only valid JSON matching the prompt schema.",
            "- Report concrete mismatches only.",
            "- Do not use skill-specific phrasing.",
        ]
    )


def _clean_cd_context(path: str | None, use_clean: bool):
    if not use_clean:
        return nullcontext(None)
    if path:
        return nullcontext(Path(path))
    return TemporaryDirectory(prefix="codex-skill-eval-")


def _new_run_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid4().hex[:8]}"


def _requires_skill(run_mode: str) -> bool:
    return run_mode in {"single", "with_skill"}


def _skill_config_override() -> str:
    return f"skills.config=[{{path={json.dumps(str(PIXEL_SKILL_DIR))},enabled=true}}]"


def _skill_setup(command: list[str], *, run_mode: str) -> dict[str, object]:
    required = _requires_skill(run_mode)
    override = _skill_config_override()
    return {
        "required": required,
        "configured": required and "-c" in command and override in command,
        "name": PIXEL_SKILL_NAME,
        "path": str(PIXEL_SKILL_DIR),
        "skill_file": str(PIXEL_SKILL_FILE),
        "sha256": _sha256_file(PIXEL_SKILL_FILE),
        "config_override": override if required else None,
    }


def _build_run_metadata(
    *,
    args: argparse.Namespace,
    run_id: str,
    cases: list[EvalCase],
    transcripts_dir: Path,
    with_cwd: Path | None,
    baseline_cwd: Path | None,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "harness": {
            "name": "pixel-perfect-design-to-code-evals",
            "version": "local",
            "runner": "skills/pixel-perfect-design-to-code/evals/run_codex_exec.py",
        },
        "target_skill": {
            "name": PIXEL_SKILL_NAME,
            "path": str(PIXEL_SKILL_FILE),
            "skill_dir": str(PIXEL_SKILL_DIR),
            "sha256": _sha256_file(PIXEL_SKILL_FILE),
        },
        "skill_config": {
            "with_skill_override": _skill_config_override(),
            "baseline_uses_ignore_user_config": bool(args.compare_baseline),
            "baseline_uses_ignore_rules": bool(args.compare_baseline),
        },
        "inputs": {
            "cases_path": str(Path(args.cases)),
            "cases_sha256": _sha256_file(Path(args.cases)),
            "template_path": str(Path(args.template)),
            "template_sha256": _sha256_file(Path(args.template)),
            "case_ids": [case.id for case in cases],
        },
        "execution": {
            "codex_bin": args.codex_bin,
            "model": args.model,
            "without_skill_model": args.without_skill_model,
            "sandbox": args.sandbox,
            "cwd": str(Path(args.cd)),
            "compare_baseline": bool(args.compare_baseline),
            "repeat": args.repeat,
            "without_skill_images": args.without_skill_images,
            "attach_images": not args.no_images,
            "json_trace": not args.no_json_trace,
            "with_skill_cwd": str(with_cwd) if with_cwd else str(Path(args.cd)),
            "baseline_cwd": str(baseline_cwd) if baseline_cwd else None,
            "transcripts_dir": str(transcripts_dir),
        },
        "artifacts": {
            "answers": str(Path(args.out)),
            "transcripts_dir": str(transcripts_dir),
        },
    }


def _transcript_path(
    transcripts_dir: Path,
    case_id: str,
    mode: str,
    *,
    attempt: int,
    repeat: int,
) -> Path:
    if mode == "single":
        suffix = "last_message" if repeat == 1 else f"attempt_{attempt}_last_message"
        return transcripts_dir / f"{case_id}_{suffix}.json"
    suffix = f"{mode}_last_message" if repeat == 1 else f"{mode}_attempt_{attempt}_last_message"
    return transcripts_dir / f"{case_id}_{suffix}.json"


def _sum_attempt_duration(attempts: object) -> float:
    if not isinstance(attempts, list):
        return 0.0
    total = 0.0
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        run = attempt.get("run")
        if isinstance(run, dict) and isinstance(run.get("duration_ms"), int | float):
            total += float(run["duration_ms"])
    return total


def build_codex_exec_command(
    case: EvalCase,
    config: CodexExecConfig,
    output_last_message: Path,
    *,
    run_mode: str = "single",
    model_override: str | None = None,
    extra_args: tuple[str, ...] = (),
    cwd_override: Path | None = None,
    ignore_user_config: bool = False,
    ignore_rules: bool = False,
) -> list[str]:
    if model_override is None:
        model_override = config.model
    cwd = cwd_override or config.cwd
    command = [
        config.codex_bin,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--sandbox",
        config.sandbox,
        "--cd",
        str(cwd),
        "--output-last-message",
        str(output_last_message),
    ]
    if _requires_skill(run_mode):
        command.extend(["-c", _skill_config_override()])
    if config.json_trace:
        command.append("--json")
    if ignore_user_config:
        command.append("--ignore-user-config")
    if ignore_rules:
        command.append("--ignore-rules")
    if model_override:
        command.extend(["--model", model_override])
    if config.attach_images:
        for image_path in _image_paths(case, run_mode=run_mode):
            command.extend(["--image", str(image_path)])
    if config.extra_args:
        command.extend(config.extra_args)
    command.extend(extra_args)
    command.append("-")
    return command


def run_case(
    case: EvalCase,
    prompt: str,
    config: CodexExecConfig,
    output_last_message: Path,
    *,
    run_mode: str = "single",
    run_id: str = "manual",
    model_override: str | None = None,
    extra_args: tuple[str, ...] = (),
    cwd_override: Path | None = None,
    ignore_user_config: bool = False,
    ignore_rules: bool = False,
) -> tuple[object, dict[str, object]]:
    if config.attach_images and run_mode != "without_skill":
        _ensure_review_artifacts(case)
    for image_path in _image_paths(case, run_mode=run_mode):
        if config.attach_images and not image_path.exists():
            raise FileNotFoundError(
                f"missing image {image_path}; run {EVALS_ROOT / 'generate_fixtures.py'}"
            )

    command = build_codex_exec_command(
        case,
        config,
        output_last_message,
        run_mode=run_mode,
        model_override=model_override,
        extra_args=extra_args,
        cwd_override=cwd_override,
        ignore_user_config=ignore_user_config,
        ignore_rules=ignore_rules,
    )
    cwd = cwd_override or config.cwd
    started_at = time.perf_counter()
    result = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
        cwd=cwd,
    )
    duration_ms = (time.perf_counter() - started_at) * 1000

    if result.returncode != 0:
        events = _parse_jsonl_events(result.stdout)
        output_last_message.write_text(
            json.dumps(
                {
                    "case_id": case.id,
                    "run_id": run_id,
                    "run_mode": run_mode,
                    "command": command,
                    "prompt": prompt,
                    "duration_ms": duration_ms,
                    "return_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "json_events": events,
                    "skill_setup": _skill_setup(command, run_mode=run_mode),
                    "trace_errors": _trace_errors(
                        events,
                        run_mode=run_mode,
                        json_trace=config.json_trace,
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            f"codex exec failed for {case.id} with exit {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    answer_raw = ""
    if output_last_message.exists():
        answer_raw = output_last_message.read_text(encoding="utf-8").strip()
    if not answer_raw:
        answer_raw = result.stdout.strip()
    if not answer_raw:
        raise RuntimeError(f"codex exec produced an empty answer for {case.id}")

    answer = _safe_parse_json(answer_raw)
    events = _parse_jsonl_events(result.stdout)
    tool_calls = _tool_calls_from_events(events)
    trace_errors = _trace_errors(events, run_mode=run_mode, json_trace=config.json_trace)

    transcript = {
        "case_id": case.id,
        "run_id": run_id,
        "run_mode": run_mode,
        "command": command,
        "prompt": prompt,
        "duration_ms": duration_ms,
        "return_code": result.returncode,
        "output_raw": answer_raw,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "json_events": events,
        "tool_calls": tool_calls,
        "skill_setup": _skill_setup(command, run_mode=run_mode),
        "trace_errors": trace_errors,
    }
    output_last_message.write_text(
        json.dumps(transcript, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    meta = {
        "duration_ms": duration_ms,
        "run_id": run_id,
        "transcript": str(output_last_message),
        "token_count": _estimate_tokens(answer_raw),
        "prompt_tokens": _estimate_tokens(prompt),
        "json_event_count": len(events),
        "tool_call_count": len(tool_calls),
        "skill_setup": _skill_setup(command, run_mode=run_mode),
        "trace_errors": trace_errors,
    }
    return answer, meta


def _parse_jsonl_events(stdout: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _trace_errors(
    events: list[dict[str, object]],
    *,
    run_mode: str = "single",
    json_trace: bool = True,
) -> list[str]:
    tool_calls = _tool_calls_from_events(events)
    errors: list[str] = []
    if tool_calls:
        errors.append(f"tool calls are forbidden in visual-diff evals: {tool_calls[0]}")
    forbidden = [
        call
        for call in tool_calls
        if any(term in call.casefold() for term in _FORBIDDEN_TRACE_TERMS)
    ]
    if forbidden:
        errors.append(f"forbidden eval artifact access in trace: {forbidden[0]}")
    return errors


def _tool_calls_from_events(events: list[dict[str, object]]) -> list[str]:
    calls: list[str] = []
    for event in events:
        calls.extend(_collect_tool_calls(event))
    deduped: list[str] = []
    for call in calls:
        if call not in deduped:
            deduped.append(call)
    return deduped


def _collect_tool_calls(value: object) -> list[str]:
    if isinstance(value, list):
        calls: list[str] = []
        for item in value:
            calls.extend(_collect_tool_calls(item))
        return calls
    if not isinstance(value, dict):
        return []

    calls = [_event_summary(value)] if _is_tool_call_event(value) else []
    for item in value.values():
        calls.extend(_collect_tool_calls(item))
    return calls


def _is_tool_call_event(event: dict[str, object]) -> bool:
    kind_text = " ".join(
        str(event.get(key, "")).casefold()
        for key in _EVENT_KIND_KEYS
        if isinstance(event.get(key), str)
    )
    if any(term in kind_text for term in _TOOL_KIND_TERMS):
        return True
    if "call" not in kind_text:
        return False
    call_names = " ".join(
        str(event.get(key, "")).casefold()
        for key in _CALL_NAME_KEYS
        if isinstance(event.get(key), str)
    )
    return any(name in call_names for name in ("exec", "shell", "tool", "function"))


def _event_summary(event: dict[str, object]) -> str:
    text = _flatten_strings(event)
    return " ".join(text.split())[:400]


def _flatten_strings(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_strings(item) for item in value.values())
    if isinstance(value, list | tuple):
        return " ".join(_flatten_strings(item) for item in value)
    return ""


def _image_paths(case: EvalCase, *, run_mode: str = "single") -> tuple[Path, ...]:
    if run_mode == "without_skill":
        return (EVALS_ROOT / public_clean_mock_path(case), EVALS_ROOT / public_clean_actual_path(case))
    return (
        EVALS_ROOT / public_clean_mock_path(case),
        EVALS_ROOT / public_clean_actual_path(case),
        *_review_artifact_paths(case),
        EVALS_ROOT / public_mock_path(case),
        EVALS_ROOT / public_actual_path(case),
    )


def _review_artifact_paths(case: EvalCase) -> tuple[Path, ...]:
    out_dir = _review_artifact_dir(case)
    prefix = public_case_label(case.id)
    base_paths = [
        out_dir / f"{prefix}_review_panel.png",
        out_dir / f"{prefix}_side_by_side.png",
        out_dir / f"{prefix}_boxes.png",
        out_dir / f"{prefix}_strict_diff.png",
        out_dir / f"{prefix}_structural_heatmap.png",
        out_dir / f"{prefix}_combined.png",
        out_dir / f"{prefix}_threshold.png",
        out_dir / f"{prefix}_edge.png",
        out_dir / f"{prefix}_target_overlay.png",
        out_dir / f"{prefix}_combined_overlay.png",
    ]
    crop_paths = sorted(out_dir.glob(f"{prefix}_M*_zoom.png"))
    return tuple(base_paths + crop_paths)


def _review_artifact_dir(case: EvalCase) -> Path:
    return EVALS_ROOT / "review_artifacts" / public_case_label(case.id)


def _ensure_review_artifacts(case: EvalCase) -> None:
    out_dir = _review_artifact_dir(case)
    prefix = public_case_label(case.id)
    required = out_dir / f"{prefix}_review_panel.png"
    target = EVALS_ROOT / public_clean_mock_path(case)
    actual = EVALS_ROOT / public_clean_actual_path(case)

    script = PIXEL_SKILL_DIR / "scripts" / "opencv_diff_boxes.py"
    ignore_rects = _ignore_rects(case)
    manifest = _review_artifact_manifest(case)
    fingerprint = _review_artifact_fingerprint(
        target=target,
        actual=actual,
        script=script,
        ignore_rects=ignore_rects,
    )
    if required.exists() and _manifest_matches(manifest, fingerprint):
        return

    command = [
        "uv",
        "run",
        "--extra",
        "opencv",
        "python",
        str(script),
        "--target",
        str(target),
        "--actual",
        str(actual),
        "--out-dir",
        str(out_dir),
        "--prefix",
        prefix,
    ]
    for rect in ignore_rects:
        command.extend(["--ignore-rect", rect])

    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "failed to generate review artifacts with opencv_diff_boxes.py\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    manifest.write_text(json.dumps(fingerprint, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _review_artifact_manifest(case: EvalCase) -> Path:
    return _review_artifact_dir(case) / f"{public_case_label(case.id)}_review_manifest.json"


def _review_artifact_fingerprint(
    *,
    target: Path,
    actual: Path,
    script: Path,
    ignore_rects: tuple[str, ...],
) -> dict[str, object]:
    return {
        "target_sha256": _sha256_file(target),
        "actual_sha256": _sha256_file(actual),
        "script_sha256": _sha256_file(script),
        "ignore_rects": list(ignore_rects),
    }


def _manifest_matches(path: Path, expected: dict[str, object]) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")) == expected
    except (OSError, json.JSONDecodeError):
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ignore_rects(case: EvalCase) -> tuple[str, ...]:
    if case.platform == "ios" or case.profile == "ios":
        return (f"0,0,{case.width},47", f"0,{case.height - 34},{case.width},34")
    if case.platform == "android" or case.profile == "android":
        return (f"0,0,{case.width},24", f"0,{case.height - 48},{case.width},48")
    return ()


def _safe_parse_json(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    return max(1, int(math.ceil(len(text) / 4)))


def _load_answers_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("answers") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("answers JSON must be a list or an object with an 'answers' list")
    answers: dict[str, object] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("answer rows must be objects")
        case_id = row.get("id")
        if not isinstance(case_id, str):
            raise ValueError("answer row is missing string id")
        answers[case_id] = row
    return answers


def write_answers_json(
    path: Path,
    answers: dict[str, object],
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for case_id, answer in sorted(answers.items()):
        if isinstance(answer, dict) and "id" in answer:
            rows.append(answer)
            continue
        rows.append({"id": case_id, "answer": answer})
    payload: dict[str, object] = {"answers": rows}
    if metadata:
        payload["run_id"] = metadata["run_id"]
        payload["run_metadata"] = metadata
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
