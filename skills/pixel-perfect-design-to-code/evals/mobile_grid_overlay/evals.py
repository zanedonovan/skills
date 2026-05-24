"""Small code-based grader for mobile visual-diff answers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExpectedFinding:
    label: str
    region_terms: tuple[str, ...]
    evidence_terms: tuple[str, ...]
    target_point: tuple[int, int] | None = None
    point_tolerance: int = 32
    target_box: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class EvalCase:
    id: str
    platform: str
    profile: str
    width: int
    height: int
    mock_path: str
    actual_path: str
    expected_findings: tuple[ExpectedFinding, ...]
    banned_false_alarms: tuple[str, ...]
    passing_score: float
    notes: str


@dataclass(frozen=True)
class GradeResult:
    case_id: str
    score: float
    passed: bool
    matched_findings: tuple[str, ...]
    missed_findings: tuple[str, ...]
    false_alarms: tuple[str, ...]
    schema_errors: tuple[str, ...] = ()


_GENERIC_EVIDENCE_TERMS = {
    "button",
    "card",
    "color",
    "continue",
    "corner",
    "cta",
    "font",
    "header",
    "radius",
    "search",
    "shift",
    "shifted",
    "spacing",
    "title",
    "vertical center",
}

def load_cases_json(path: Path) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("cases JSON must be a list or an object with a 'cases' list")
    return [_case_from_json(row) for row in rows]


def load_answers_json(path: Path) -> dict[str, object]:
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
        answers[case_id] = row.get("answer", row.get("with_skill", {}))
    return answers


def build_prompt(case: EvalCase, template: str) -> str:
    return template.format(
        id=case.id,
        case_label=public_case_label(case.id),
        platform=case.platform,
        profile=case.profile,
        width=case.width,
        height=case.height,
        mock_path=public_mock_path(case),
        actual_path=public_actual_path(case),
        notes=case.notes,
    )


def public_case_label(case_id: str) -> str:
    digest = hashlib.sha1(case_id.encode("utf-8")).hexdigest()[:8]
    return f"case-{digest}"


def public_mock_path(case: EvalCase) -> str:
    return f"public/{public_case_label(case.id)}_mock.png"


def public_actual_path(case: EvalCase) -> str:
    return f"public/{public_case_label(case.id)}_actual.png"


def public_clean_mock_path(case: EvalCase) -> str:
    return f"public/{public_case_label(case.id)}_mock_clean.png"


def public_clean_actual_path(case: EvalCase) -> str:
    return f"public/{public_case_label(case.id)}_actual_clean.png"


def grade_answer(case: EvalCase, answer: object) -> GradeResult:
    schema_errors = validate_answer_schema(case, answer)
    finding_texts = _finding_texts_for_grading(answer)
    grading_answer = "\n".join(finding_texts)
    normalized_answer = _normalize(grading_answer)
    matched: list[str] = []
    missed: list[str] = []

    for expected in case.expected_findings:
        if any(_finding_matches_expected(text, expected) for text in finding_texts):
            matched.append(expected.label)
        else:
            missed.append(expected.label)

    false_alarms = tuple(
        term for term in case.banned_false_alarms if term and _contains_term(normalized_answer, term)
    )
    base_score = len(matched) / len(case.expected_findings) if case.expected_findings else 1.0
    score = max(0.0, base_score - 0.15 * len(false_alarms))
    if schema_errors:
        score = 0.0
    return GradeResult(
        case_id=case.id,
        score=round(score, 3),
        passed=not schema_errors and score >= case.passing_score,
        matched_findings=tuple(matched),
        missed_findings=tuple(missed),
        false_alarms=false_alarms,
        schema_errors=schema_errors,
    )


def validate_answer_schema(case: EvalCase, answer: object) -> tuple[str, ...]:
    structured = _load_structured_answer(answer)
    if not isinstance(structured, dict):
        return ("answer must be a JSON object",)
    findings = structured.get("findings")
    if not isinstance(findings, list):
        return ("findings must be a list",)

    errors: list[str] = []
    required = ("severity", "cells", "mask_id", "point", "component", "difference", "evidence")
    for index, finding in enumerate(findings):
        prefix = f"findings[{index}]"
        if not isinstance(finding, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in required:
            if key not in finding:
                errors.append(f"{prefix}.{key} is required")

        severity = finding.get("severity")
        if severity not in {"high", "medium", "low"}:
            errors.append(f"{prefix}.severity must be high, medium, or low")

        cells = finding.get("cells")
        if not isinstance(cells, list) or not cells:
            errors.append(f"{prefix}.cells must be a non-empty list")
        elif not all(isinstance(cell, str) and re.fullmatch(r"[A-D][1-8]", cell.upper()) for cell in cells):
            errors.append(f"{prefix}.cells must contain A1-D8 cell labels")

        mask_id = finding.get("mask_id")
        if not isinstance(mask_id, str) or not re.fullmatch(r"none|M[1-9][0-9]*", mask_id):
            errors.append(f"{prefix}.mask_id must be none or M<number>")

        point = finding.get("point")
        if not _is_valid_point(point, case.width, case.height):
            errors.append(f"{prefix}.point must be [x, y] inside the screenshot bounds")

        for key in ("component", "difference", "evidence"):
            value = finding.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{key} must be a non-empty string")

    summary = structured.get("summary")
    if summary is not None and not isinstance(summary, str):
        errors.append("summary must be a string when present")
    return tuple(errors)


def _is_valid_point(value: object, width: int, height: int) -> bool:
    if not isinstance(value, list | tuple) or len(value) != 2:
        return False
    x, y = value
    if not isinstance(x, int) or not isinstance(y, int):
        return False
    return 0 <= x < width and 0 <= y < height


def answer_text_for_grading(answer: object) -> str:
    return "\n".join(_finding_texts_for_grading(answer))


def _finding_texts_for_grading(answer: object) -> tuple[str, ...]:
    structured = _load_structured_answer(answer)
    if not isinstance(structured, dict):
        return ()
    findings = structured.get("findings")
    if not isinstance(findings, list):
        return ()
    rendered = [_render_structured_finding(finding) for finding in findings if isinstance(finding, dict)]
    rendered = [finding for finding in rendered if finding]
    return tuple(rendered)


def _finding_matches_expected(text: str, finding: ExpectedFinding) -> bool:
    normalized = _normalize(text)
    region_hit = _has_required_region(normalized, finding.region_terms)
    evidence_hit = _contains_evidence(normalized, finding.evidence_terms)
    target_hit = _contains_target_point(
        text,
        finding.target_point,
        finding.point_tolerance,
        finding.target_box,
    )
    return region_hit and evidence_hit and target_hit


def _load_structured_answer(answer: object) -> object | None:
    if isinstance(answer, dict):
        return answer
    if not isinstance(answer, str):
        return None
    try:
        return json.loads(answer)
    except json.JSONDecodeError:
        return None


def _render_structured_finding(finding: dict[str, object]) -> str:
    point = finding.get("point")
    if isinstance(point, list | tuple) and len(point) >= 2:
        point_text = f"{point[0]},{point[1]}"
    elif isinstance(point, str):
        point_text = point
    else:
        point_text = ""
    cells = finding.get("cells")
    if isinstance(cells, list | tuple):
        cells_text = ",".join(str(cell) for cell in cells)
    else:
        cells_text = str(cells or "")
    parts = [
        f"severity: {finding.get('severity', '')}",
        f"cells: {cells_text}",
        f"mask_id: {finding.get('mask_id', '')}",
        f"point: {point_text}",
        f"component: {finding.get('component', '')}",
        f"difference: {finding.get('difference', '')}",
        f"evidence: {finding.get('evidence', '')}",
    ]
    return "; ".join(parts)


def _case_from_json(row: object) -> EvalCase:
    if not isinstance(row, dict):
        raise ValueError("case rows must be objects")
    return EvalCase(
        id=_required_str(row, "id"),
        platform=_required_str(row, "platform"),
        profile=_required_str(row, "profile"),
        width=int(row["width"]),
        height=int(row["height"]),
        mock_path=_required_str(row, "mock_path"),
        actual_path=_required_str(row, "actual_path"),
        expected_findings=_parse_expected_findings_json(row.get("expected_findings")),
        banned_false_alarms=_terms_from_json(row.get("banned_false_alarms", [])),
        passing_score=float(row.get("passing_score") or 1.0),
        notes=str(row.get("notes", "")),
    )


def _parse_expected_findings_json(raw: object) -> tuple[ExpectedFinding, ...]:
    if not isinstance(raw, list):
        raise ValueError("expected_findings must be a list")
    findings: list[ExpectedFinding] = []
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("expected finding rows must be objects")
        target_point, point_tolerance, target_box = _parse_target_json(row.get("target"))
        findings.append(
            ExpectedFinding(
                label=_required_str(row, "label"),
                region_terms=_terms_from_json(row.get("region_terms", [])),
                evidence_terms=_terms_from_json(row.get("evidence_terms", [])),
                target_point=target_point,
                point_tolerance=point_tolerance,
                target_box=target_box,
            )
        )
    return tuple(findings)


def _parse_target_json(raw: object) -> tuple[tuple[int, int] | None, int, tuple[int, int, int, int] | None]:
    if raw is None:
        return None, 32, None
    if not isinstance(raw, dict):
        raise ValueError("target must be an object")
    if "box" in raw:
        box = raw["box"]
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("target.box must be [x1, y1, x2, y2]")
        x1, y1, x2, y2 = (int(value) for value in box)
        tolerance = int(raw.get("tolerance", 0))
        return ((x1 + x2) // 2, (y1 + y2) // 2), tolerance, (x1, y1, x2, y2)
    point = raw.get("point")
    if not isinstance(point, list) or len(point) != 2:
        raise ValueError("target.point must be [x, y]")
    return (int(point[0]), int(point[1])), int(raw.get("tolerance", 32)), None


def _required_str(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing string field {key}")
    return value


def _terms_from_json(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError("terms must be a list")
    return tuple(_normalize(str(term)) for term in raw if str(term).strip())


def _normalize(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"[\s_\-]+", " ", text)
    return re.sub(r"[^a-z0-9.% ]+", " ", text)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _contains_evidence(text: str, terms: tuple[str, ...]) -> bool:
    if _denies_mismatch(text):
        return False
    distinctive_terms = tuple(term for term in terms if term not in _GENERIC_EVIDENCE_TERMS)
    return _contains_any(text, distinctive_terms or terms)


def _contains_target_point(
    answer: str,
    target_point: tuple[int, int] | None,
    point_tolerance: int,
    target_box: tuple[int, int, int, int] | None,
) -> bool:
    if target_point is None:
        return True
    if target_box is not None:
        return any(_inside_box(point, target_box, point_tolerance) for point in _answer_points(answer))
    return any(_distance(point, target_point) <= point_tolerance for point in _answer_points(answer))


def _answer_points(answer: str) -> tuple[tuple[int, int], ...]:
    points: list[tuple[int, int]] = []
    for match in re.finditer(
        r"\b(?:point|target)\s*[:=]?\s*\"?\(?\s*(\d+)\s*,\s*(\d+)",
        answer,
        re.I,
    ):
        points.append((int(match.group(1)), int(match.group(2))))
    return tuple(points)


def _distance(first: tuple[int, int], second: tuple[int, int]) -> float:
    return ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5


def _inside_box(point: tuple[int, int], box: tuple[int, int, int, int], margin: int) -> bool:
    x1, y1, x2, y2 = box
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    return left - margin <= point[0] <= right + margin and top - margin <= point[1] <= bottom + margin


def _has_required_region(text: str, terms: tuple[str, ...]) -> bool:
    grid_cells = tuple(term for term in terms if re.fullmatch(r"[a-z]\d+", term))
    if grid_cells:
        return _contains_any(text, grid_cells)
    return _contains_any(text, terms)


def _contains_term(text: str, term: str) -> bool:
    term = _normalize(term)
    if not term:
        return False
    if term in text:
        return True
    words = tuple(word for word in term.split(" ") if word)
    if len(words) <= 1:
        return False
    tokens = re.findall(r"[a-z0-9]+", text)
    span = len(words) + 3
    for index in range(0, max(0, len(tokens) - len(words) + 1)):
        window = tokens[index : index + span]
        if all(word in window for word in words):
            return True
    return False


def _denies_mismatch(text: str) -> bool:
    denial_phrases = (
        "no visual difference",
        "no mismatch",
        "no differences",
        "cannot find a difference",
        "not purple",
        "not missing",
        "not shifted",
        "not too round",
        "not rounded",
        "not square",
        "not sharp",
        "radius matches",
        "corners match",
        "corner radius matches",
    )
    return any(phrase in text for phrase in denial_phrases)
