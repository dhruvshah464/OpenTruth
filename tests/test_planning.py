from pathlib import Path

from opentruth.planning import expand
from opentruth.requirement import load_requirements


def test_load_and_expand(tmp_path: Path) -> None:
    path = tmp_path / "requirements.yaml"
    path.write_text(
        'requirement: "A user can create an account and sign in."\n'
        "constraints:\n"
        "  - duplicate emails rejected\n"
        "  - invalid password rejected\n"
        "  - session persists after refresh\n",
        encoding="utf-8",
    )
    req = load_requirements(path)
    assert req.id == "R-1"
    assert [c.id for c in req.constraints] == ["C-0", "C-1", "C-2", "C-3"]
    assert req.constraints[0].kind == "happy_path"
    plan = expand(req, "http://127.0.0.1:9", email="a@example.test")
    cited = {s["constraint_id"] for s in plan["steps"]}
    assert cited == {"C-0", "C-1", "C-2", "C-3"}
    reload_idx = next(i for i, s in enumerate(plan["steps"]) if s["kind"] == "reload")
    second_signup = next(
        i
        for i, s in enumerate(plan["steps"])
        if s["kind"] == "navigate" and str(s.get("url", "")).endswith("/signup") and i > 0
    )
    assert reload_idx < second_signup
    assert plan["actor"]["email"] == "a@example.test"
    for step in plan["steps"]:
        assert "constraint_id" in step
        assert step["id"].startswith("S-")
