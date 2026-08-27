from pathlib import Path

from opentruth.planning import expand
from opentruth.requirement import load_requirements

ROOT = Path(__file__).resolve().parents[1]
STATE_REQ = ROOT / "examples" / "miniauth" / "requirements-state.yaml"


def test_expand_state_mixes_http_and_sql() -> None:
    req = load_requirements(STATE_REQ)
    plan = expand(req, "http://127.0.0.1:9", email="a@example.test", mode="state")
    assert plan["mode"] == "state"
    assert plan["runner"] == "state"
    kinds = {s["kind"] for s in plan["steps"]}
    assert "http_request" in kinds
    assert "sql_query" in kinds
    cited = {s["constraint_id"] for s in plan["steps"]}
    assert cited == {"C-0", "C-1", "C-2", "C-3"}
    identity_sql = [
        s for s in plan["steps"] if s["kind"] == "sql_query" and "identities" in s["sql"]
    ]
    assert identity_sql and identity_sql[0]["constraint_id"] == "C-2"
    user_sql = [s for s in plan["steps"] if s["kind"] == "sql_query" and "FROM users" in s["sql"]]
    assert user_sql
