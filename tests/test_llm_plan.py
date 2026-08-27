import json
import urllib.request
from pathlib import Path

import pytest

from opentruth.engine import verify
from opentruth.llm import (
    HttpChatProposer,
    PlanError,
    build_plan,
    parse_json_object,
    sanitize_plan,
)
from opentruth.planning import expand
from opentruth.requirement import load_requirements
from opentruth.store import load_json
from opentruth.verdicts import NOT_PROVEN, PARTIALLY_PROVEN

ROOT = Path(__file__).resolve().parents[1]
MINIAUTH = ROOT / "examples" / "miniauth"
MINIAUTH_REQ = MINIAUTH / "requirements.yaml"


class ScriptedProposer:
    model = "scripted-test"

    def __init__(self, payload: str | dict):
        self.payload = payload
        self.prompts: list[str] = []

    def propose(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload)


class DownProposer:
    model = "down"

    def propose(self, prompt: str) -> str:
        raise TimeoutError("model down")


def _req():
    return load_requirements(MINIAUTH_REQ)


def _actor():
    return {"email": "a@example.test", "password": "correct-horse-battery"}


def test_parse_json_object_from_fence() -> None:
    assert parse_json_object('```json\n{"steps": [1]}\n```') == {"steps": [1]}
    with pytest.raises(PlanError):
        parse_json_object("not json")


def test_sanitize_strips_verdict_and_renumbers() -> None:
    req = _req()
    det = expand(req, "http://127.0.0.1:9", email="a@example.test", mode="api")
    poisoned = {**det, "verdict": "PROVEN", "confidence": 1.0, "summary": {"proven": 1}}
    plan = sanitize_plan(poisoned, req, "api", "http://127.0.0.1:9", det["actor"], det.get("routes"))
    assert "verdict" not in plan
    assert "confidence" not in plan
    assert "summary" not in plan
    assert plan["mode"] == "api"
    assert plan["requirement_id"] == "R-1"
    assert [s["id"] for s in plan["steps"]] == [f"S-{i:03d}" for i in range(1, len(plan["steps"]) + 1)]
    assert {s["constraint_id"] for s in plan["steps"]} == {"C-0", "C-1", "C-2", "C-3", "C-4"}


def test_sanitize_rejects_hostile_kind() -> None:
    req = _req()
    raw = {"steps": [{"kind": "shell", "constraint_id": "C-0", "command": "rm -rf /"}]}
    with pytest.raises(PlanError, match="hostile"):
        sanitize_plan(raw, req, "api", "http://127.0.0.1:9", _actor())


def test_sanitize_drops_unknown_constraint_and_bad_sql() -> None:
    req = _req()
    raw = {
        "steps": [
            {
                "kind": "http_request",
                "constraint_id": "C-0",
                "method": "POST",
                "path": "/api/signup",
                "json": {"email": "a@example.test"},
            },
            {"kind": "http_request", "constraint_id": "C-99", "method": "GET", "path": "/api/me"},
            {
                "kind": "sql_query",
                "constraint_id": "C-1",
                "sql": "DROP TABLE users",
                "params": {"email": "a@example.test"},
            },
        ]
    }
    plan = sanitize_plan(raw, req, "api", "http://127.0.0.1:9", _actor())
    assert [s["constraint_id"] for s in plan["steps"]] == ["C-0"]
    assert all(s["kind"] != "sql_query" for s in plan["steps"])


def test_sanitize_allows_count_sql_in_state_mode() -> None:
    req = load_requirements(MINIAUTH / "requirements-state.yaml")
    raw = {
        "steps": [
            {
                "kind": "sql_query",
                "constraint_id": "C-1",
                "sql": "SELECT COUNT(*) AS n FROM users WHERE email = :email",
                "params": {"email": "a@example.test"},
            }
        ]
    }
    plan = sanitize_plan(raw, req, "state", "http://127.0.0.1:9", _actor())
    assert plan["steps"][0]["sql"].upper().startswith("SELECT COUNT")


def test_build_plan_default_is_deterministic() -> None:
    plan = build_plan(_req(), "http://127.0.0.1:9", "api")
    assert plan["planner"] == "deterministic"
    assert "llm_error" not in plan


def test_build_plan_missing_key_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENTRUTH_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plan = build_plan(_req(), "http://127.0.0.1:9", "api", llm=True)
    assert plan["planner"] == "deterministic"
    assert plan["planner_requested"] == "llm"
    assert "OPENTRUTH_LLM_API_KEY missing" in plan["llm_error"]


def test_http_proposer_reads_chat_content(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": '{"ok":true}'}}]}).encode()

    def fake_open(req: urllib.request.Request, timeout: float | None = None) -> Resp:
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization") or ""
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    proposer = HttpChatProposer("https://example.test/v1", "sk-test", "not-the-builder")
    assert proposer.propose("hello") == '{"ok":true}'
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert "sk-test" in captured["auth"]


def test_llm_scripted_plan_cannot_assign_verdict(tmp_path: Path) -> None:
    req = _req()
    det = expand(req, "http://example.invalid", email="stub@example.test", mode="api")
    det["verdict"] = "PROVEN"
    det["confidence"] = 1.0
    proposer = ScriptedProposer(det)
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=False, mode="api", llm=proposer)
    assert proposer.prompts, "LLM proposer must be asked for a plan"
    assert result["verdict"]["requirements"][0]["verdict"] == PARTIALLY_PROVEN
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan["planner"] == "llm"
    assert plan["planner_model"] == "scripted-test"
    assert "verdict" not in plan
    stored = load_json(result["run_dir"] / "verdict.json")
    assert stored["requirements"][0]["verdict"] == PARTIALLY_PROVEN


def test_llm_down_falls_back_to_deterministic(tmp_path: Path) -> None:
    result = verify(
        MINIAUTH,
        runs_root=tmp_path,
        persist_session=False,
        mode="api",
        llm=DownProposer(),
    )
    assert result["verdict"]["requirements"][0]["verdict"] == PARTIALLY_PROVEN
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan["planner"] == "deterministic"
    assert plan["planner_requested"] == "llm"
    assert "model down" in plan["llm_error"]


def test_llm_verdict_only_payload_is_not_authoritative(tmp_path: Path) -> None:
    proposer = ScriptedProposer({"verdict": "PROVEN", "confidence": 1, "steps": []})
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=False, mode="api", llm=proposer)
    assert result["verdict"]["requirements"][0]["verdict"] == PARTIALLY_PROVEN
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan["planner"] == "deterministic"
    assert "no steps" in plan["llm_error"]


def test_llm_thin_plan_is_not_proven(tmp_path: Path) -> None:
    """A model that only covers C-0 cannot skip the rest into PROVEN."""
    proposer = ScriptedProposer(
        {
            "steps": [
                {
                    "kind": "http_request",
                    "constraint_id": "C-0",
                    "method": "POST",
                    "path": "/api/signup",
                    "json": {"email": "thin@example.test", "password": "correct-horse-battery"},
                },
                {"kind": "assert", "constraint_id": "C-0", "check": "status_equals", "expect": "201"},
                {
                    "kind": "http_request",
                    "constraint_id": "C-0",
                    "method": "POST",
                    "path": "/api/login",
                    "json": {"email": "thin@example.test", "password": "correct-horse-battery"},
                },
                {"kind": "assert", "constraint_id": "C-0", "check": "status_equals", "expect": "200"},
            ]
        }
    )
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=False, mode="api", llm=proposer)
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == NOT_PROVEN
    by_id = {row["id"]: row["result"] for row in req["constraints"]}
    assert by_id["C-0"] == "pass"
    assert by_id["C-3"] == "inconclusive"
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan["planner"] == "llm"
    assert "verdict" not in plan
