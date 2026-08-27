from opentruth.assertions import evaluate
from opentruth.verdicts import FAIL, INCONCLUSIVE, PASS


def test_status_equals() -> None:
    obs = [{"id": "O-001", "kind": "http", "status": 401}]
    result, cites, _ = evaluate("status_equals", "401", obs)
    assert result == PASS
    assert cites == ["O-001"]
    result, _, _ = evaluate("status_equals", "200", obs)
    assert result == FAIL
    result, _, _ = evaluate("status_equals", "200", [])
    assert result == INCONCLUSIVE


def test_cell_equals() -> None:
    obs = [{"id": "O-002", "kind": "state", "rows": [{"n": 0}], "error": None}]
    result, cites, _ = evaluate("cell_equals", "1", obs, extra={"column": "n"})
    assert result == FAIL
    assert cites == ["O-002"]
    obs[0]["rows"] = [{"n": 1}]
    result, _, _ = evaluate("cell_equals", "1", obs, extra={"column": "n"})
    assert result == PASS
