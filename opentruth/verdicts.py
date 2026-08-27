"""Roll E-* assertions up to C-* then R-*. Verdict is derived, never an LLM opinion."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from opentruth.requirement import Requirement

PASS = "pass"
FAIL = "fail"
INCONCLUSIVE = "inconclusive"

IMPROVED = "improved"
REGRESSED = "regressed"
UNCHANGED = "unchanged"
CHANGED = "changed"

PROVEN = "PROVEN"
PARTIALLY_PROVEN = "PARTIALLY_PROVEN"
FAILED = "FAILED"
NOT_PROVEN = "NOT_PROVEN"
INCONCLUSIVE_V = "INCONCLUSIVE"


def delta(left: str | None, right: str | None) -> str:
    """Classify a constraint-level change between two sealed runs."""
    if left is None and right is None:
        return UNCHANGED
    if left == right:
        return UNCHANGED
    if left != PASS and right == PASS:
        return IMPROVED
    if left == PASS and right != PASS:
        return REGRESSED
    return CHANGED


def roll_diff(deltas: Iterable[str], right_results: Iterable[str], integrity_ok: bool) -> str:
    """Verdict for 'the change satisfied the requirement without regressions'."""
    deltas = list(deltas)
    rights = list(right_results)
    if not integrity_ok:
        return INCONCLUSIVE_V
    if any(d == REGRESSED for d in deltas):
        return FAILED
    if any(r == INCONCLUSIVE for r in rights) or any(d == CHANGED for d in deltas):
        return NOT_PROVEN
    if all(r == PASS for r in rights) and rights:
        return PROVEN
    if any(d == IMPROVED for d in deltas) and any(r == FAIL for r in rights):
        return PARTIALLY_PROVEN
    return NOT_PROVEN


def roll_constraint(results: Iterable[str]) -> str:
    values = list(results)
    if not values:
        return INCONCLUSIVE
    if FAIL in values:
        return FAIL
    if INCONCLUSIVE in values:
        return INCONCLUSIVE
    return PASS


def roll_requirement(happy: str, others: Iterable[str]) -> str:
    others = list(others)
    if happy == FAIL:
        return FAILED
    if happy == INCONCLUSIVE:
        return INCONCLUSIVE_V
    if happy != PASS:
        return INCONCLUSIVE_V
    if any(r == FAIL for r in others):
        return PARTIALLY_PROVEN
    if any(r == INCONCLUSIVE for r in others):
        return NOT_PROVEN
    return PROVEN


def confidence(assertions: Iterable[dict[str, Any]]) -> float:
    conclusive = [a for a in assertions if a.get("result") in (PASS, FAIL)]
    if not conclusive:
        return 0.0
    passed = sum(1 for a in conclusive if a["result"] == PASS)
    return passed / len(conclusive)


def build_verdict(
    run_id: str,
    requirement: Requirement,
    assertions: list[dict[str, Any]],
) -> dict[str, Any]:
    by_c: dict[str, list[str]] = defaultdict(list)
    for assertion in assertions:
        by_c[assertion["constraint_id"]].append(assertion["result"])
    constraint_rows = []
    for constraint in requirement.constraints:
        constraint_rows.append(
            {
                "id": constraint.id,
                "kind": constraint.kind,
                "statement": constraint.statement,
                "result": roll_constraint(by_c.get(constraint.id, [])),
            }
        )
    happy = next(row for row in constraint_rows if row["kind"] == "happy_path")
    others = [row["result"] for row in constraint_rows if row["kind"] != "happy_path"]
    req_verdict = roll_requirement(happy["result"], others)
    conf = confidence(assertions)
    req_block = {
        "id": requirement.id,
        "statement": requirement.statement,
        "verdict": req_verdict,
        "confidence": conf,
        "constraints": constraint_rows,
    }
    summary = {
        "requirements": 1,
        "proven": int(req_verdict == PROVEN),
        "partially_proven": int(req_verdict == PARTIALLY_PROVEN),
        "failed": int(req_verdict == FAILED),
        "not_proven": int(req_verdict == NOT_PROVEN),
        "inconclusive": int(req_verdict == INCONCLUSIVE_V),
        "confidence": conf,
        "critical_failures": int(req_verdict == FAILED),
    }
    return {"run_id": run_id, "requirements": [req_block], "summary": summary}


def exit_code(verdict_name: str) -> int:
    """CI contract: 0 only for PROVEN; 2 for inability; 1 for product failure."""
    if verdict_name == PROVEN:
        return 0
    if verdict_name == INCONCLUSIVE_V:
        return 2
    return 1
