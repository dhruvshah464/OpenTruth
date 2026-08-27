from opentruth.verdicts import (
    CHANGED,
    FAIL,
    FAILED,
    IMPROVED,
    INCONCLUSIVE,
    INCONCLUSIVE_V,
    NOT_PROVEN,
    PARTIALLY_PROVEN,
    PASS,
    PROVEN,
    REGRESSED,
    UNCHANGED,
    build_verdict,
    confidence,
    delta,
    roll_constraint,
    roll_diff,
    roll_requirement,
)
from opentruth.requirement import Requirement, Constraint


def test_constraint_roll() -> None:
    assert roll_constraint([PASS, PASS]) == PASS
    assert roll_constraint([PASS, FAIL]) == FAIL
    assert roll_constraint([PASS, INCONCLUSIVE]) == INCONCLUSIVE
    assert roll_constraint([]) == INCONCLUSIVE


def test_requirement_roll() -> None:
    assert roll_requirement(PASS, [PASS, PASS]) == PROVEN
    assert roll_requirement(PASS, [PASS, FAIL]) == PARTIALLY_PROVEN
    assert roll_requirement(FAIL, [PASS]) == FAILED
    assert roll_requirement(INCONCLUSIVE, [PASS]) == INCONCLUSIVE_V


def test_confidence_excludes_inconclusive() -> None:
    assertions = [
        {"result": PASS},
        {"result": PASS},
        {"result": FAIL},
        {"result": INCONCLUSIVE},
    ]
    assert confidence(assertions) == 2 / 3


def test_build_verdict_partial() -> None:
    req = Requirement(
        id="R-1",
        statement="auth",
        constraints=(
            Constraint("C-0", "R-1", "auth", "happy_path"),
            Constraint("C-3", "R-1", "session persists after refresh", "constraint"),
        ),
    )
    assertions = [
        {"constraint_id": "C-0", "result": PASS},
        {"constraint_id": "C-3", "result": FAIL},
    ]
    verdict = build_verdict("abc", req, assertions)
    assert verdict["requirements"][0]["verdict"] == PARTIALLY_PROVEN
    assert verdict["summary"]["partially_proven"] == 1
    assert verdict["summary"]["critical_failures"] == 0


def test_delta_classifies_constraint_change() -> None:
    assert delta(PASS, PASS) == UNCHANGED
    assert delta(FAIL, FAIL) == UNCHANGED
    assert delta(FAIL, PASS) == IMPROVED
    assert delta(INCONCLUSIVE, PASS) == IMPROVED
    assert delta(None, PASS) == IMPROVED
    assert delta(PASS, FAIL) == REGRESSED
    assert delta(PASS, INCONCLUSIVE) == REGRESSED
    assert delta(PASS, None) == REGRESSED
    assert delta(FAIL, INCONCLUSIVE) == CHANGED
    assert delta(INCONCLUSIVE, FAIL) == CHANGED


def test_roll_diff_verdicts() -> None:
    all_pass = [PASS, PASS, PASS]
    assert roll_diff([UNCHANGED, UNCHANGED, UNCHANGED], all_pass, True) == PROVEN
    assert roll_diff([IMPROVED, UNCHANGED, UNCHANGED], all_pass, True) == PROVEN
    assert (
        roll_diff([IMPROVED, UNCHANGED], [PASS, FAIL], True) == PARTIALLY_PROVEN
    )
    assert roll_diff([REGRESSED, UNCHANGED], [FAIL, PASS], True) == FAILED
    assert roll_diff([UNCHANGED, UNCHANGED], [FAIL, PASS], True) == NOT_PROVEN
    assert roll_diff([CHANGED, UNCHANGED], [INCONCLUSIVE, PASS], True) == NOT_PROVEN
    assert roll_diff([UNCHANGED], [INCONCLUSIVE], True) == NOT_PROVEN
    assert roll_diff([IMPROVED], [PASS], False) == INCONCLUSIVE_V
