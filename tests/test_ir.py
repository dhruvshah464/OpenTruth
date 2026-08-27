"""Verification IR: parse → validate → normalize → compile → plan.json."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from opentruth.engine import verify
from opentruth.ir import IrError, compile_verification
from opentruth.llm import build_plan
from opentruth.planning import expand
from opentruth.requirement import load_requirement_document, load_requirements
from opentruth.store import load_json, load_jsonl
from opentruth.verdicts import INCONCLUSIVE_V, NOT_PROVEN, PARTIALLY_PROVEN, PROVEN

MINIAUTH = Path(__file__).resolve().parents[1] / "examples" / "miniauth"

SIGNUP_IR = """
requirement: "Signup creates an account."
constraints:
  - statement: "A second signup with the same mailbox is refused."
verification:
  version: 1
  steps:
    - id: S-1
      constraint: C-0
      http_request:
        method: POST
        path: /api/signup
        json:
          email: "{{actor.email}}"
          password: "{{actor.password}}"
    - id: S-2
      constraint: C-0
      assert:
        check: status_equals
        expect: "201"
    - id: S-3
      constraint: C-1
      http_request:
        method: POST
        path: /api/signup
        json:
          email: "{{actor.email}}"
          password: "{{actor.password}}"
    - id: S-4
      constraint: C-1
      assert:
        check: status_equals
        expect: "409"
"""

THIN_IR = """
requirement: "Signup creates an account."
constraints:
  - statement: "A second signup with the same mailbox is refused."
verification:
  version: 1
  steps:
    - id: S-1
      constraint: C-0
      http_request:
        method: POST
        path: /api/signup
        json:
          email: "{{actor.email}}"
          password: "{{actor.password}}"
    - id: S-2
      constraint: C-0
      assert:
        check: status_equals
        expect: "201"
"""


def _actor() -> dict[str, str]:
    return {"email": "ir@example.test", "password": "correct-horse-battery"}


def _document(tmp_path: Path, text: str):
    path = tmp_path / "requirements.yaml"
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return load_requirement_document(path)


def _app_with_yaml(tmp_path: Path, text: str) -> Path:
    dest = tmp_path / "app"
    shutil.copytree(
        MINIAUTH,
        dest,
        ignore=shutil.ignore_patterns(".opentruth*", ".opentruth-tmp*", "__pycache__", "*.pyc"),
    )
    (dest / "requirements.yaml").write_text(text.strip() + "\n", encoding="utf-8")
    return dest


class RecordingProposer:
    model = "should-not-run"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def propose(self, prompt: str) -> str:
        self.prompts.append(prompt)
        raise AssertionError("declared IR must not call the LLM")


def test_expander_does_not_keyword_match_mailbox_wording(tmp_path: Path) -> None:
    doc = _document(tmp_path, SIGNUP_IR.split("verification:")[0])
    plan = expand(doc.requirement, "http://127.0.0.1:9", email="a@example.test", mode="api")
    c1 = [s for s in plan["steps"] if s["constraint_id"] == "C-1"]
    assert c1
    assert c1[0]["check"] == "unsupported_constraint"


def test_compile_nested_yaml_to_plan_kinds(tmp_path: Path) -> None:
    doc = _document(tmp_path, SIGNUP_IR)
    plan = compile_verification(
        doc.verification, doc.requirement, "api", "http://127.0.0.1:9", _actor()
    )
    assert plan["planner"] == "ir"
    assert plan["verification_version"] == 1
    assert [s["id"] for s in plan["steps"]] == ["S-1", "S-2", "S-3", "S-4"]
    assert plan["steps"][0]["kind"] == "http_request"
    assert plan["steps"][0]["json"]["email"] == "ir@example.test"
    assert plan["steps"][1]["kind"] == "assert"
    assert plan["steps"][1]["check"] == "status_equals"
    assert {s["constraint_id"] for s in plan["steps"]} == {"C-0", "C-1"}


def test_compile_rejects_unknown_version(tmp_path: Path) -> None:
    doc = _document(tmp_path, SIGNUP_IR)
    verification = dict(doc.verification)
    verification["version"] = 99
    with pytest.raises(IrError, match="unsupported verification.version"):
        compile_verification(verification, doc.requirement, "api", "http://127.0.0.1:9", _actor())


def test_compile_rejects_missing_version(tmp_path: Path) -> None:
    doc = _document(tmp_path, SIGNUP_IR)
    verification = dict(doc.verification)
    del verification["version"]
    with pytest.raises(IrError, match="version is required"):
        compile_verification(verification, doc.requirement, "api", "http://127.0.0.1:9", _actor())


def test_compile_rejects_hostile_kind(tmp_path: Path) -> None:
    doc = _document(tmp_path, SIGNUP_IR)
    verification = {
        "version": 1,
        "steps": [{"id": "S-x", "constraint": "C-0", "shell": {"command": "rm -rf /"}}],
    }
    with pytest.raises(IrError, match="hostile"):
        compile_verification(verification, doc.requirement, "api", "http://127.0.0.1:9", _actor())


def test_compile_rejects_unknown_constraint(tmp_path: Path) -> None:
    doc = _document(tmp_path, SIGNUP_IR)
    verification = {
        "version": 1,
        "steps": [
            {
                "id": "S-1",
                "constraint": "C-99",
                "http_request": {"method": "GET", "path": "/api/me"},
            }
        ],
    }
    with pytest.raises(IrError, match="unknown constraint"):
        compile_verification(verification, doc.requirement, "api", "http://127.0.0.1:9", _actor())


def test_compile_rejects_sql_in_api_mode(tmp_path: Path) -> None:
    doc = _document(tmp_path, SIGNUP_IR)
    verification = {
        "version": 1,
        "steps": [
            {
                "id": "S-1",
                "constraint": "C-0",
                "sql_query": {
                    "sql": "SELECT COUNT(*) AS n FROM users WHERE email = :email",
                    "params": {"email": "{{actor.email}}"},
                },
            }
        ],
    }
    with pytest.raises(IrError, match="not allowed"):
        compile_verification(verification, doc.requirement, "api", "http://127.0.0.1:9", _actor())


def test_build_plan_ir_beats_llm(tmp_path: Path) -> None:
    doc = _document(tmp_path, SIGNUP_IR)
    proposer = RecordingProposer()
    plan = build_plan(
        doc.requirement,
        "http://127.0.0.1:9",
        "api",
        llm=proposer,
        verification=doc.verification,
    )
    assert plan["planner"] == "ir"
    assert proposer.prompts == []


def test_build_plan_without_verification_stays_deterministic() -> None:
    req = load_requirements(MINIAUTH / "requirements.yaml")
    plan = build_plan(req, "http://127.0.0.1:9", "api")
    assert plan["planner"] == "deterministic"


def test_ir_signup_without_keyword_match_is_proven(tmp_path: Path) -> None:
    app = _app_with_yaml(tmp_path, SIGNUP_IR)
    result = verify(app, runs_root=tmp_path / "runs", persist_session=False, mode="api")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == PROVEN
    rows = {row["id"]: row["result"] for row in req["constraints"]}
    assert rows["C-0"] == "pass"
    assert rows["C-1"] == "pass"
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan["planner"] == "ir"
    assert plan["verification_version"] == 1


def test_ir_missing_coverage_is_not_proven(tmp_path: Path) -> None:
    app = _app_with_yaml(tmp_path, THIN_IR)
    result = verify(app, runs_root=tmp_path / "runs", persist_session=False, mode="api")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == NOT_PROVEN
    rows = {row["id"]: row["result"] for row in req["constraints"]}
    assert rows["C-0"] == "pass"
    assert rows["C-1"] == "inconclusive"
    assertions = load_jsonl(result["run_dir"] / "assertions.jsonl")
    coverage = [a for a in assertions if a.get("check") == "coverage"]
    assert coverage
    assert coverage[0]["constraint_id"] == "C-1"
    assert coverage[0]["result"] == "inconclusive"


def test_ir_hostile_verify_does_not_expand(tmp_path: Path) -> None:
    text = yaml.safe_load(SIGNUP_IR)
    text["verification"]["steps"] = [
        {"id": "S-x", "constraint": "C-0", "shell": {"command": "true"}}
    ]
    app = _app_with_yaml(tmp_path, yaml.safe_dump(text))
    proposer = RecordingProposer()
    result = verify(
        app,
        runs_root=tmp_path / "runs",
        persist_session=False,
        mode="api",
        llm=proposer,
    )
    assert proposer.prompts == []
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan["planner"] == "ir"
    assert "hostile" in plan["ir_error"]
    assert result["verdict"]["requirements"][0]["verdict"] == INCONCLUSIVE_V


def test_miniauth_default_yaml_still_uses_expander(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=False, mode="api")
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan["planner"] == "deterministic"
    assert "verification_version" not in plan
    assert result["verdict"]["requirements"][0]["verdict"] == PARTIALLY_PROVEN
