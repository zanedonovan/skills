from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from eval_suite import load_pixel_eval_module


run_codex_exec = load_pixel_eval_module("run_codex_exec")
skill_contracts = load_pixel_eval_module("skill_contracts")
_baseline_prompt = run_codex_exec._baseline_prompt
_live_prompt = run_codex_exec._live_prompt
PIXEL_SKILL_NAME = skill_contracts.PIXEL_SKILL_NAME
PIXEL_STATE_PATH = skill_contracts.PIXEL_STATE_PATH
activation_eval_cases = skill_contracts.activation_eval_cases
expected_activation = skill_contracts.expected_activation
grade_activation_trace = skill_contracts.grade_activation_trace
grade_resume_trace_reads_state_first = skill_contracts.grade_resume_trace_reads_state_first
grade_subagent_trace = skill_contracts.grade_subagent_trace


ROOT = Path(__file__).resolve().parents[5]
SKILL = ROOT / "skills" / "pixel-perfect-design-to-code" / "skills" / "pixel-perfect-design-to-code"
GOAL_REPORT = SKILL / "scripts" / "goal_report.py"


def _load_goal_report():
    spec = importlib.util.spec_from_file_location("goal_report", GOAL_REPORT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load goal_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _verified_metadata(target: Path, current: Path) -> dict[str, object]:
    return {
        "width": 390,
        "height": 844,
        "inputs": {
            "target_sha256": _sha256(target),
            "actual_sha256": _sha256(current),
        },
        "ignore_regions": [],
        "layers": [],
        "score": {
            "source": "opencv_diff_boxes",
            "overall": 0.91,
            "threshold_diff_ratio": 0.001,
            "edge_diff_ratio": 0.002,
            "combined_diff_ratio": 0.003,
            "threshold_pixels": 10,
            "edge_pixels": 20,
            "combined_pixels": 30,
            "total_pixels": 10000,
            "box_count": 2,
        },
        "boxes": [],
        "crops": [],
        "outputs": {},
    }


@pytest.mark.eval
@pytest.mark.fast
def test_activation_eval_cases_have_expected_trigger_boundary() -> None:
    cases = activation_eval_cases()

    assert any(case.should_activate for case in cases)
    assert any(not case.should_activate for case in cases)
    for case in cases:
        assert expected_activation(case.prompt) is case.should_activate, case.reason


@pytest.mark.eval
@pytest.mark.fast
def test_live_and_baseline_prompts_encode_activation_and_non_activation() -> None:
    active_prompt = _live_prompt("Compare target and current screenshots.")
    baseline_prompt = _baseline_prompt("Compare target and current screenshots.")

    assert "Use the $pixel-perfect-design-to-code skill" in active_prompt
    assert "Do not use any Codex skills" in baseline_prompt
    assert "including pixel-perfect-design-to-code" in baseline_prompt
    assert "Do not use skill-specific phrasing" in baseline_prompt


@pytest.mark.eval
@pytest.mark.fast
def test_activation_trace_eval_requires_actual_event_not_final_text_claim() -> None:
    user_prompt_trace = [
        {
            "type": "message",
            "role": "user",
            "content": f"Use the {PIXEL_SKILL_NAME} skill.",
        }
    ]
    claim_only_trace = [
        {
            "type": "message",
            "role": "assistant",
            "content": f"I used the {PIXEL_SKILL_NAME} skill.",
        }
    ]
    actual_activation_trace = [
        {
            "type": "skill_activation",
            "name": PIXEL_SKILL_NAME,
            "path": f"skills/{PIXEL_SKILL_NAME}/skills/{PIXEL_SKILL_NAME}/SKILL.md",
        }
    ]
    context_activation_trace = [
        {
            "type": "context_item",
            "item_type": "skill",
            "name": PIXEL_SKILL_NAME,
        }
    ]

    assert not grade_activation_trace(user_prompt_trace).passed
    assert not grade_activation_trace(claim_only_trace).passed
    assert grade_activation_trace(actual_activation_trace).passed
    assert grade_activation_trace(context_activation_trace).passed
    unexpected = grade_activation_trace(actual_activation_trace, should_activate=False)
    assert not unexpected.passed
    assert f"unexpected skill activation trace: {PIXEL_SKILL_NAME}" in unexpected.errors


@pytest.mark.eval
@pytest.mark.fast
def test_subagent_trace_eval_requires_actual_call_not_final_text_claim() -> None:
    claim_only_trace = [
        {
            "type": "message",
            "role": "assistant",
            "content": "I used pixel-spark-explorer and pixel-spark-worker.",
        }
    ]
    actual_call_trace = [
        {
            "type": "tool_call",
            "name": "pixel-spark-explorer",
            "arguments": {"question": "Map M1 to code ownership."},
        },
        {
            "type": "tool_call",
            "name": "pixel-spark-worker",
            "arguments": {"mission": "Adjust CTA vertical padding."},
        },
    ]

    failed = grade_subagent_trace(
        claim_only_trace,
        required_agents=("pixel-spark-explorer",),
    )
    passed = grade_subagent_trace(
        actual_call_trace,
        required_agents=("pixel-spark-explorer", "pixel-spark-worker"),
    )

    assert not failed.passed
    assert "missing actual sub-agent call: pixel-spark-explorer" in failed.errors
    assert passed.passed
    assert "pixel-spark-explorer" in passed.evidence
    assert "pixel-spark-worker" in passed.evidence


@pytest.mark.eval
@pytest.mark.fast
def test_resume_trace_eval_requires_state_read_before_other_actions() -> None:
    good_trace = [
        {
            "type": "tool_call",
            "name": "exec_command",
            "arguments": {"cmd": f"sed -n '1,200p' {PIXEL_STATE_PATH}"},
        },
        {
            "type": "tool_call",
            "name": "exec_command",
            "arguments": {"cmd": "sed -n '1,120p' src/App.tsx"},
        },
    ]
    bad_trace = [
        {
            "type": "tool_call",
            "name": "exec_command",
            "arguments": {"cmd": "sed -n '1,120p' src/App.tsx"},
        },
        {
            "type": "tool_call",
            "name": "exec_command",
            "arguments": {"cmd": f"cat {PIXEL_STATE_PATH}"},
        },
    ]

    assert grade_resume_trace_reads_state_first(good_trace).passed
    failed = grade_resume_trace_reads_state_first(bad_trace)
    assert not failed.passed
    assert f"first action after resume did not read {PIXEL_STATE_PATH}" in failed.errors


@pytest.mark.eval
@pytest.mark.fast
def test_compaction_resume_contract_is_present_in_docs_and_generated_state(tmp_path: Path) -> None:
    report = _load_goal_report()
    target = tmp_path / "target.png"
    current = tmp_path / "current.png"
    metadata = tmp_path / "iter-00_metadata.json"
    out = tmp_path / "report.html"
    state = tmp_path / "state.md"
    target.write_bytes(b"target")
    current.write_bytes(b"current")
    metadata.write_text(json.dumps(_verified_metadata(target, current)), encoding="utf-8")

    exit_code = report.main(
        [
            "--target",
            str(target),
            "--screenshot",
            str(current),
            "--metadata",
            str(metadata),
            "--width",
            "390",
            "--height",
            "844",
            "--max-iterations",
            "3",
            "--out",
            str(out),
            "--state-out",
            str(state),
            "--require-verified-score",
            "--next-step",
            "Read state, inspect latest review pair, then patch only the CTA mismatch.",
        ]
    )

    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    goal_loop = (SKILL / "references" / "goal-loop.md").read_text(encoding="utf-8")
    state_text = state.read_text(encoding="utf-8")

    assert exit_code == 0
    assert out.is_file()
    assert "Read this file first after context compaction" in state_text
    assert "- Latest iteration: 0" in state_text
    assert "iter-00_metadata.json" in state_text
    assert "Read state, inspect latest review pair" in state_text
    assert "Before making another patch, confirm `.pixel-goal/state.md` names the latest iteration" in skill_text
    assert "After compaction, read `.pixel-goal/state.md` first" in goal_loop
    assert "Do not rely on the old chat transcript" in goal_loop


@pytest.mark.eval
@pytest.mark.fast
def test_subagent_contract_rejects_generated_artifact_edits() -> None:
    worker = (SKILL / "agents" / "pixel-spark-worker.toml").read_text(encoding="utf-8")
    reviewer = (SKILL / "agents" / "pixel-smart-reviewer.toml").read_text(encoding="utf-8")
    subagents = (SKILL / "references" / "subagents.md").read_text(encoding="utf-8")

    assert "Never change generated .pixel-goal artifacts" in worker
    assert "generated-artifact edits" in reviewer
    assert "Treat any worker diff that touches `.pixel-goal/**` as a rejected worker result" in subagents
    assert "Regenerate those artifacts only through the scorer/report commands" in subagents
