from pathlib import Path

from opentruth.planning import expand
from opentruth.requirement import load_requirements

ROOT = Path(__file__).resolve().parents[1]
MINIAUTH_REQ = ROOT / "examples" / "miniauth" / "requirements.yaml"


def test_expand_api_uses_http_steps() -> None:
    req = load_requirements(MINIAUTH_REQ)
    plan = expand(req, "http://127.0.0.1:9", email="a@example.test", mode="api")
    assert plan["mode"] == "api"
    assert plan["runner"] == "http"
    kinds = {s["kind"] for s in plan["steps"]}
    assert "http_request" in kinds
    assert "navigate" not in kinds
    cited = {s["constraint_id"] for s in plan["steps"]}
    assert cited == {"C-0", "C-1", "C-2", "C-3", "C-4"}
    persist = [s for s in plan["steps"] if s["constraint_id"] == "C-3" and s["kind"] == "http_request"]
    assert persist and persist[0]["path"] == "/api/me"
    unauth = [s for s in plan["steps"] if s["constraint_id"] == "C-4" and s["kind"] == "http_request"]
    assert unauth and unauth[0].get("cookies") is False
    # Second /api/me (persist) must happen before later signup/login noise.
    first_me_after_happy = None
    signup_dup = None
    for i, step in enumerate(plan["steps"]):
        if step["kind"] == "http_request" and step.get("path") == "/api/me" and step["constraint_id"] == "C-3":
            first_me_after_happy = i
        if step["kind"] == "http_request" and step.get("path") == "/api/signup" and step["constraint_id"] == "C-1":
            signup_dup = i
    assert first_me_after_happy is not None and signup_dup is not None
    assert first_me_after_happy < signup_dup
